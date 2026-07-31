//+------------------------------------------------------------------+
//|                                            TradeZuluCopier.mq5   |
//|                                                                  |
//|  Copies trades between MetaTrader accounts, with TradeZulu doing  |
//|  the deciding. Attach it to one chart on every terminal you want  |
//|  involved -- the master and each slave -- and set nothing else.   |
//|  The server already knows which account is which.                 |
//|                                                                  |
//|  There is no Python and no IPC here, deliberately. MetaTrader's   |
//|  Python API does not work reliably under Wine, but an Expert      |
//|  Advisor runs inside the terminal where none of that matters, and |
//|  WebRequest is a first-class MetaTrader feature.                  |
//|                                                                  |
//|  BEFORE IT WILL RUN:                                              |
//|    Tools -> Options -> Expert Advisors                            |
//|      [x] Allow algorithmic trading                                |
//|      [x] Allow WebRequest for listed URL   -> add your TradeZulu  |
//|          origin, e.g. http://tradezulu.local:8420                 |
//+------------------------------------------------------------------+
#property copyright "TradeZulu"
#property version   "1.00"
#property strict
#property description "Copies trades to and from a TradeZulu server."

input group "Connection"
input string ServerUrl        = "http://192.168.1.10:8420/api"; // TradeZulu API base URL (ends with /api)
input string ApiKey           = "";                             // TZ_INGEST_TOKEN from the server's .env
input int    RequestTimeoutMs = 15000;                          // WebRequest timeout (ms)

input group "Behaviour"
input int    PollSeconds      = 2;     // How often to report in. The server can ask for slower.
input int    Slippage         = 20;    // Maximum deviation, in points
input int    MagicNumber      = 0;     // Stamped on copied orders; 0 leaves it unset
input bool   Verbose          = true;  // Log every command to the Experts tab

input group "Journal"
input bool   SendHistory      = true;  // Send closed deals so the journal fills itself
input int    HistorySeconds   = 60;    // How often to look for new ones
input int    FirstSyncDays    = 730;   // How far back to go the first time
input int    DealsPerRequest  = 200;   // Batch size; a long history is sent in pieces
input bool   UploadCandles    = true;  // Send bars around each trade, so charts have something to draw
input ENUM_TIMEFRAMES CandleTimeframe = PERIOD_M15;  // Which timeframe to send
input int    CandlesBefore    = 150;   // Bars before the entry
input int    CandlesAfter     = 80;    // Bars after the exit
input int    CandleBackfillDays = 60;  // How far back to fetch charts for trades already journalled

//--- state ----------------------------------------------------------
string g_status       = "starting";
string g_pending      = "";   // results waiting to go back on the next poll
int    g_done         = 0;
int    g_failed       = 0;
int    g_poll_seconds = 0;

//--- journal --------------------------------------------------------
ulong    g_last_ticket  = 0;      // highest deal the server already has
bool     g_cursor_known = false;
datetime g_next_history = 0;
int      g_sent_deals   = 0;
bool     g_candles_done = false;   // the one-off backfill for trades already journalled

//--- stops seen on live positions -----------------------------------
// MetaTrader records a stop on the *order*, so a stop attached after entry --
// trailed, or dragged onto the chart -- never reaches the deal history. A
// journal reading history alone therefore cannot tell what such a trade
// risked, and every R figure for it would be wrong.
//
// The remedy is to watch: this EA already reads open positions every couple of
// seconds, so it remembers the tightest stop it ever saw on each one and
// attaches that to the entry deal when the position closes.
ulong  g_pos_id[];
double g_pos_sl[];
double g_pos_tp[];

//+------------------------------------------------------------------+
int OnInit()
{
   if(StringLen(ApiKey) == 0)
   {
      Print("TradeZulu: ApiKey is empty. Set it to the value of TZ_INGEST_TOKEN.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(StringFind(ServerUrl, "http") != 0)
   {
      Print("TradeZulu: ServerUrl must start with http:// or https://");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      Print("TradeZulu: algorithmic trading is switched off in this terminal. "
            "Reads will work; orders will be refused until you allow it.");

   g_poll_seconds = MathMax(1, PollSeconds);
   EventSetTimer(1);   // first tick promptly, then settle to the agreed rate
   Print("TradeZulu copier: started, reporting to ", ServerUrl);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
   Print("TradeZulu copier: stopped (reason ", reason, ")");
}

//+------------------------------------------------------------------+
void OnTimer()
{
   static bool first = true;
   if(first)
   {
      first = false;
      EventKillTimer();
      EventSetTimer(g_poll_seconds);
   }
   Poll();

   // The journal runs on its own clock. Copying is worth doing every couple of
   // seconds; history is not, and walking it that often would spend the whole
   // timer on deals that have not changed.
   if(SendHistory && TimeCurrent() >= g_next_history)
   {
      g_next_history = TimeCurrent() + (datetime)MathMax(10, HistorySeconds);
      SendClosedDeals();
   }

   ShowStatus();
}

//--- JSON building --------------------------------------------------
string JsonEscape(string text)
{
   StringReplace(text, "\\", "\\\\");
   StringReplace(text, "\"", "\\\"");
   StringReplace(text, "\n", " ");
   StringReplace(text, "\r", " ");
   StringReplace(text, "\t", " ");
   return text;
}

string JStr(const string key, const string value)
{
   return StringFormat("\"%s\":\"%s\"", key, JsonEscape(value));
}

string JNum(const string key, const double value, const int digits = 8)
{
   return StringFormat("\"%s\":%s", key, DoubleToString(value, digits));
}

string JInt(const string key, const long value)
{
   return StringFormat("\"%s\":%I64d", key, value);
}

string JBool(const string key, const bool value)
{
   return StringFormat("\"%s\":%s", key, value ? "true" : "false");
}

//--- JSON reading ---------------------------------------------------
// Small by design: the only JSON this EA ever parses is its own server's
// reply, whose shape is fixed. A general parser would be more code than the
// protocol deserves.
string JsonValue(const string json, const string key, const int from = 0)
{
   string needle = "\"" + key + "\":";
   int at = StringFind(json, needle, from);
   if(at < 0)
      return "";
   int start = at + StringLen(needle);
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ')
      start++;
   if(start >= StringLen(json))
      return "";

   if(StringGetCharacter(json, start) == '"')
   {
      int end = StringFind(json, "\"", start + 1);
      if(end < 0)
         return "";
      return StringSubstr(json, start + 1, end - start - 1);
   }
   int end = start;
   while(end < StringLen(json))
   {
      ushort c = StringGetCharacter(json, end);
      if(c == ',' || c == '}' || c == ']')
         break;
      end++;
   }
   string raw = StringSubstr(json, start, end - start);
   StringTrimLeft(raw);
   StringTrimRight(raw);
   return raw;
}

//--- what we tell the server ----------------------------------------
int FindPosition(const ulong position_id)
{
   for(int i = 0; i < ArraySize(g_pos_id); i++)
      if(g_pos_id[i] == position_id)
         return i;
   return -1;
}

void RememberStops(const ulong position_id, const double sl, const double tp)
{
   if(position_id == 0)
      return;
   int at = FindPosition(position_id);
   if(at < 0)
   {
      at = ArraySize(g_pos_id);
      ArrayResize(g_pos_id, at + 1);
      ArrayResize(g_pos_sl, at + 1);
      ArrayResize(g_pos_tp, at + 1);
      g_pos_id[at] = position_id;
      g_pos_sl[at] = 0.0;
      g_pos_tp[at] = 0.0;
   }
   // Keep the first real stop seen rather than the latest. A stop that has
   // been trailed into profit is no longer what the trade risked, and using
   // it would flatter every R figure it touches.
   if(g_pos_sl[at] == 0.0 && sl != 0.0) g_pos_sl[at] = sl;
   if(g_pos_tp[at] == 0.0 && tp != 0.0) g_pos_tp[at] = tp;
}

string PositionsJson()
{
   string out = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      RememberStops((ulong)PositionGetInteger(POSITION_IDENTIFIER),
                    PositionGetDouble(POSITION_SL),
                    PositionGetDouble(POSITION_TP));
      if(StringLen(out) > 0)
         out += ",";
      long type = PositionGetInteger(POSITION_TYPE);
      out += "{" + JInt("position_id", (long)PositionGetInteger(POSITION_IDENTIFIER));
      out += "," + JInt("ticket", (long)ticket);
      out += "," + JStr("symbol", PositionGetString(POSITION_SYMBOL));
      out += "," + JStr("direction", type == POSITION_TYPE_BUY ? "long" : "short");
      out += "," + JNum("volume", PositionGetDouble(POSITION_VOLUME), 2);
      out += "," + JNum("open_price", PositionGetDouble(POSITION_PRICE_OPEN), 8);
      out += "," + JNum("stop_loss", PositionGetDouble(POSITION_SL), 8);
      out += "," + JNum("take_profit", PositionGetDouble(POSITION_TP), 8);
      out += "," + JNum("profit", PositionGetDouble(POSITION_PROFIT), 2);
      out += "}";
   }
   return "[" + out + "]";
}

// Only the symbols that matter: what is open here, plus what Market Watch
// shows. Sending the broker's entire catalogue would be a megabyte a tick.
string SymbolsJson()
{
   string out = "";
   int total = SymbolsTotal(true);
   for(int i = 0; i < total && i < 200; i++)
   {
      string name = SymbolName(i, true);
      if(StringLen(name) == 0)
         continue;
      double tick_size  = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_VALUE);
      double per_unit   = (tick_size > 0.0) ? tick_value / tick_size : 0.0;

      if(StringLen(out) > 0)
         out += ",";
      out += "{" + JStr("symbol", name);
      out += "," + JNum("volume_min",  SymbolInfoDouble(name, SYMBOL_VOLUME_MIN), 4);
      out += "," + JNum("volume_max",  SymbolInfoDouble(name, SYMBOL_VOLUME_MAX), 4);
      out += "," + JNum("volume_step", SymbolInfoDouble(name, SYMBOL_VOLUME_STEP), 4);
      out += "," + JNum("value_per_unit", per_unit, 6);
      out += "," + JInt("digits", (long)SymbolInfoInteger(name, SYMBOL_DIGITS));
      out += "}";
   }
   return "[" + out + "]";
}

string PollBody()
{
   string body = "{";
   body += JStr("login",   IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)));
   body += "," + JStr("server",   AccountInfoString(ACCOUNT_SERVER));
   body += "," + JStr("name",     AccountInfoString(ACCOUNT_NAME));
   body += "," + JStr("currency", AccountInfoString(ACCOUNT_CURRENCY));
   body += "," + JNum("balance",     AccountInfoDouble(ACCOUNT_BALANCE), 2);
   body += "," + JNum("equity",      AccountInfoDouble(ACCOUNT_EQUITY), 2);
   body += "," + JNum("margin_free", AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2);
   body += "," + JBool("trade_allowed", TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0);
   body += ",\"positions\":" + PositionsJson();
   body += ",\"symbols\":" + SymbolsJson();
   body += ",\"results\":[" + g_pending + "]";
   body += "}";
   return body;
}

//--- the heartbeat --------------------------------------------------
void Poll()
{
   string reply;
   if(!HttpPost("/agent/poll", PollBody(), reply))
   {
      g_status = "server unreachable";
      return;
   }

   // Everything we just reported was accepted, so stop resending it.
   g_pending = "";

   int wanted = (int)StringToInteger(JsonValue(reply, "poll_seconds"));
   if(wanted > 0 && wanted != g_poll_seconds)
   {
      g_poll_seconds = wanted;
      EventKillTimer();
      EventSetTimer(g_poll_seconds);
   }

   string role = JsonValue(reply, "role");
   bool   halted = JsonValue(reply, "halted") == "true";
   g_status = halted ? "halted by the server" : role;

   RunCommands(reply);
}

void RunCommands(const string reply)
{
   int at = StringFind(reply, "\"commands\":[");
   if(at < 0)
      return;
   int cursor = at;
   while(true)
   {
      int open_brace = StringFind(reply, "{", cursor);
      if(open_brace < 0)
         break;
      int close_brace = StringFind(reply, "}", open_brace);
      if(close_brace < 0)
         break;
      string cmd = StringSubstr(reply, open_brace, close_brace - open_brace + 1);
      cursor = close_brace + 1;
      Execute(cmd);
   }
}

void Execute(const string cmd)
{
   string id      = JsonValue(cmd, "id");
   string action  = JsonValue(cmd, "action");
   string symbol  = JsonValue(cmd, "symbol");
   string dirn    = JsonValue(cmd, "direction");
   double volume  = StringToDouble(JsonValue(cmd, "volume"));
   double sl      = StringToDouble(JsonValue(cmd, "stop_loss"));
   double tp      = StringToDouble(JsonValue(cmd, "take_profit"));
   long   ticket  = StringToInteger(JsonValue(cmd, "ticket"));
   long   master  = StringToInteger(JsonValue(cmd, "master_position_id"));
   string comment = JsonValue(cmd, "comment");

   if(StringLen(id) == 0 || StringLen(action) == 0)
      return;

   if(Verbose)
      Print("TradeZulu: ", action, " ", symbol, " ", DoubleToString(volume, 2),
            " (master ", master, ")");

   bool   ok = false;
   string message = "";
   ulong  got_ticket = 0;
   double got_price = 0.0;
   int    retcode = 0;

   if(action == "open")
      ok = DoOpen(symbol, dirn, volume, sl, tp, comment, got_ticket, got_price, retcode, message);
   else if(action == "close")
      ok = DoClose((ulong)ticket, retcode, message);
   else if(action == "modify")
      ok = DoModify((ulong)ticket, sl, tp, retcode, message);
   else
      message = "unknown command";

   if(ok) g_done++; else g_failed++;

   // Held until the next poll rather than sent immediately: one round trip
   // instead of two, and a dropped result simply repeats.
   string r = "{" + JStr("id", id) + "," + JStr("action", action);
   r += "," + JBool("ok", ok);
   r += "," + JInt("ticket", (long)got_ticket);
   r += "," + JInt("master_position_id", master);
   r += "," + JStr("symbol", symbol);
   r += "," + JStr("direction", dirn);
   r += "," + JNum("volume", volume, 2);
   r += "," + JNum("price", got_price, 8);
   r += "," + JInt("retcode", retcode);
   r += "," + JStr("message", message);
   r += "}";
   if(StringLen(g_pending) > 0)
      g_pending += ",";
   g_pending += r;
}

//--- trading --------------------------------------------------------
bool DoOpen(const string symbol, const string dirn, const double volume,
            const double sl, const double tp, const string comment,
            ulong &out_ticket, double &out_price, int &retcode, string &message)
{
   if(!SymbolSelect(symbol, true))
   {
      message = "this broker has no symbol " + symbol;
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      message = "no price for " + symbol;
      return false;
   }

   bool is_long = (dirn == "long");

   MqlTradeRequest  req;
   MqlTradeResult   res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = symbol;
   req.volume       = NormalizeVolume(symbol, volume);
   req.type         = is_long ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.price        = is_long ? tick.ask : tick.bid;
   req.deviation    = Slippage;
   req.magic        = MagicNumber;
   req.comment      = comment;
   req.type_time    = ORDER_TIME_GTC;
   req.type_filling = FillingFor(symbol);
   if(sl > 0.0) req.sl = sl;
   if(tp > 0.0) req.tp = tp;

   if(req.volume <= 0.0)
   {
      message = "volume rounds to zero for this broker";
      return false;
    }

   if(!OrderSend(req, res))
   {
      retcode = (int)res.retcode;
      message = StringFormat("order rejected (%d) %s", res.retcode, res.comment);
      return false;
   }
   retcode    = (int)res.retcode;
   out_ticket = res.order > 0 ? res.order : res.deal;
   out_price  = res.price;

   if(res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_PLACED)
   {
      message = StringFormat("order not filled (%d) %s", res.retcode, res.comment);
      return false;
   }

   // Prefer the position id: that is what a later close will need.
   if(PositionSelectByTicket(out_ticket))
      out_ticket = (ulong)PositionGetInteger(POSITION_TICKET);

   message = "filled at " + DoubleToString(res.price, 8);
   return true;
}

bool DoClose(const ulong ticket, int &retcode, string &message)
{
   if(!PositionSelectByTicket(ticket))
   {
      // Already gone is the outcome we wanted, so this is not a failure.
      message = "the position was already closed";
      return true;
   }

   string symbol = PositionGetString(POSITION_SYMBOL);
   bool   is_long = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      message = "no price for " + symbol;
      return false;
   }

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = symbol;
   req.volume       = PositionGetDouble(POSITION_VOLUME);
   req.type         = is_long ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   req.position     = ticket;
   req.price        = is_long ? tick.bid : tick.ask;
   req.deviation    = Slippage;
   req.magic        = (long)PositionGetInteger(POSITION_MAGIC);
   req.comment      = "TZ close";
   req.type_time    = ORDER_TIME_GTC;
   req.type_filling = FillingFor(symbol);

   if(!OrderSend(req, res))
   {
      retcode = (int)res.retcode;
      message = StringFormat("close rejected (%d) %s", res.retcode, res.comment);
      return false;
   }
   retcode = (int)res.retcode;
   if(res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_PLACED)
   {
      message = StringFormat("close not filled (%d) %s", res.retcode, res.comment);
      return false;
   }
   message = "closed at " + DoubleToString(res.price, 8);
   return true;
}

bool DoModify(const ulong ticket, const double sl, const double tp,
              int &retcode, string &message)
{
   if(!PositionSelectByTicket(ticket))
   {
      message = "the position is no longer open";
      return true;
   }

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action   = TRADE_ACTION_SLTP;
   req.symbol   = PositionGetString(POSITION_SYMBOL);
   req.position = ticket;
   req.sl       = sl;
   req.tp       = tp;

   if(!OrderSend(req, res))
   {
      retcode = (int)res.retcode;
      message = StringFormat("modify rejected (%d) %s", res.retcode, res.comment);
      return false;
   }
   retcode = (int)res.retcode;
   if(res.retcode != TRADE_RETCODE_DONE)
   {
      message = StringFormat("modify not applied (%d) %s", res.retcode, res.comment);
      return false;
   }
   message = "stops updated";
   return true;
}

// Brokers differ on what they accept, and sending the wrong mode is rejected
// rather than corrected, so ask the symbol instead of assuming.
ENUM_ORDER_TYPE_FILLING FillingFor(const string symbol)
{
   long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((mode & SYMBOL_FILLING_IOC) != 0)
      return ORDER_FILLING_IOC;
   if((mode & SYMBOL_FILLING_FOK) != 0)
      return ORDER_FILLING_FOK;
   return ORDER_FILLING_RETURN;
}

// Round *down* to the broker's step. Up would risk more than the server
// approved, which is the one direction that must never happen quietly.
double NormalizeVolume(const string symbol, const double volume)
{
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0)
      step = 0.01;

   double out = MathFloor(volume / step + 1e-8) * step;
   out = NormalizeDouble(out, 2);
   if(out > vmax) out = vmax;
   if(out < vmin) return 0.0;
   return out;
}

//--- plumbing -------------------------------------------------------
bool HttpGet(const string path, string &reply)
{
   string url = ServerUrl + path;
   string headers = "X-API-Key: " + ApiKey + "\r\n";

   char post[];
   char result[];
   string result_headers;
   ArrayResize(post, 0);

   ResetLastError();
   int status = WebRequest("GET", url, headers, RequestTimeoutMs, post, result, result_headers);
   if(status == -1)
   {
      int error = GetLastError();
      if(error == 4014)
         Print("TradeZulu: WebRequest is not allowed for ", url,
               ". Add it under Tools -> Options -> Expert Advisors.");
      else
         Print("TradeZulu: WebRequest failed for ", url, " (error ", error, ")");
      return false;
   }

   reply = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return (status >= 200 && status < 300);
}

//--- the journal ----------------------------------------------------
//
// Closed deals are what the journal is made of, and only the terminal can
// see them: a deal exists in the account's history and nowhere else. The
// copier already talks to the server every couple of seconds, so it carries
// them too rather than asking anyone to run a second Expert Advisor.
//
// Sending is driven by a cursor the server hands out, so a restart re-sends
// nothing and a terminal that was off for a week catches up by itself. The
// server keys deals by ticket, so a duplicate is a no-op even if one slips
// through.

double ValuePerUnit(const string symbol)
{
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0.0)
      return 0.0;
   return tick_value / tick_size;
}

string DealJson(const ulong deal_ticket)
{
   string symbol       = HistoryDealGetString(deal_ticket, DEAL_SYMBOL);
   ulong  order_ticket = (ulong)HistoryDealGetInteger(deal_ticket, DEAL_ORDER);
   long   entry        = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);

   // The stop is the denominator for every R figure in the journal, so it is
   // worth two attempts. First the entry order, which has it when the stop was
   // set with the trade; then whatever was seen on the live position, which is
   // the only way to know about a stop attached afterwards.
   double sl = 0.0, tp = 0.0;
   if(entry == DEAL_ENTRY_IN)
   {
      if(order_ticket > 0)
      {
         // Already in the cache from HistorySelect(); HistoryOrderSelect() here
         // would throw away the deal list being walked.
         sl = HistoryOrderGetDouble(order_ticket, ORDER_SL);
         tp = HistoryOrderGetDouble(order_ticket, ORDER_TP);
      }
      int seen = FindPosition((ulong)HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID));
      if(seen >= 0)
      {
         if(sl == 0.0) sl = g_pos_sl[seen];
         if(tp == 0.0) tp = g_pos_tp[seen];
      }
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   string out = "{";
   out += JInt("ticket", (long)deal_ticket);
   out += "," + JInt("order", (long)order_ticket);
   out += "," + JInt("position_id", HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID));
   out += "," + JStr("symbol", symbol);
   out += "," + JInt("type",  HistoryDealGetInteger(deal_ticket, DEAL_TYPE));
   out += "," + JInt("entry", entry);
   out += "," + JNum("volume", HistoryDealGetDouble(deal_ticket, DEAL_VOLUME), 2);
   out += "," + JNum("price",  HistoryDealGetDouble(deal_ticket, DEAL_PRICE), digits);
   out += "," + JNum("profit", HistoryDealGetDouble(deal_ticket, DEAL_PROFIT), 2);
   out += "," + JNum("commission", HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION), 2);
   out += "," + JNum("swap", HistoryDealGetDouble(deal_ticket, DEAL_SWAP), 2);
   out += "," + JNum("fee",  HistoryDealGetDouble(deal_ticket, DEAL_FEE), 2);
   out += "," + JNum("sl", sl, digits);
   out += "," + JNum("tp", tp, digits);
   out += "," + JInt("magic", HistoryDealGetInteger(deal_ticket, DEAL_MAGIC));
   out += "," + JStr("comment", HistoryDealGetString(deal_ticket, DEAL_COMMENT));
   out += "," + JInt("time", HistoryDealGetInteger(deal_ticket, DEAL_TIME));
   out += "," + JNum("value_per_unit", ValuePerUnit(symbol), 6);
   out += "," + JInt("digits", digits);
   out += "}";
   return out;
}

string AccountJson()
{
   string out = "{";
   out += JInt("login", AccountInfoInteger(ACCOUNT_LOGIN));
   out += "," + JStr("name",    AccountInfoString(ACCOUNT_NAME));
   out += "," + JStr("server",  AccountInfoString(ACCOUNT_SERVER));
   out += "," + JStr("company", AccountInfoString(ACCOUNT_COMPANY));
   out += "," + JStr("currency", AccountInfoString(ACCOUNT_CURRENCY));
   out += "," + JInt("leverage", AccountInfoInteger(ACCOUNT_LEVERAGE));
   out += "," + JNum("balance", AccountInfoDouble(ACCOUNT_BALANCE), 2);
   out += "," + JNum("equity",  AccountInfoDouble(ACCOUNT_EQUITY), 2);
   out += "}";
   return out;
}

void FetchCursor()
{
   string reply;
   string path = "/mt5/cursor?login=" + (string)AccountInfoInteger(ACCOUNT_LOGIN);
   if(!HttpGet(path, reply))
      return;

   g_last_ticket  = (ulong)StringToInteger(JsonValue(reply, "last_deal_ticket"));
   g_cursor_known = true;
   if(Verbose)
      Print("TradeZulu: journal already has deals up to ticket ", g_last_ticket);
}

string TimeframeName(const ENUM_TIMEFRAMES timeframe)
{
   switch(timeframe)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
   }
   return "M15";
}

// Bars around one trade, so the journal can draw where it happened. Without
// these the chart has nothing to plot and shows an empty panel, which reads as
// broken rather than as "no data was collected".
string CandlesJson(const string symbol, const datetime from, const datetime to)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int span = PeriodSeconds(CandleTimeframe);
   datetime start = from - (datetime)(span * MathMax(1, CandlesBefore));
   datetime end   = to   + (datetime)(span * MathMax(1, CandlesAfter));

   int got = CopyRates(symbol, CandleTimeframe, start, end, rates);
   if(got <= 0)
      return "";

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   string bars = "";
   for(int i = 0; i < got; i++)
   {
      if(i > 0) bars += ",";
      bars += "{" + JInt("time", (long)rates[i].time);
      bars += "," + JNum("open",  rates[i].open,  digits);
      bars += "," + JNum("high",  rates[i].high,  digits);
      bars += "," + JNum("low",   rates[i].low,   digits);
      bars += "," + JNum("close", rates[i].close, digits);
      bars += "," + JNum("volume", (double)rates[i].tick_volume, 0);
      bars += "}";
   }
   return "{" + JStr("symbol", symbol)
        + "," + JStr("timeframe", TimeframeName(CandleTimeframe))
        + ",\"candles\":[" + bars + "]}";
}

bool PostDeals(const string deals)
{
   string body = "{" + JStr("source", "ea")
               + ",\"account\":" + AccountJson()
               + ",\"deals\":[" + deals + "]}";
   string reply;
   if(!HttpPost("/mt5/ingest", body, reply))
      return false;
   return true;
}

void TrackWindow(string &symbols[], datetime &first[], datetime &last[],
                 const string symbol, const datetime when)
{
   for(int i = 0; i < ArraySize(symbols); i++)
   {
      if(symbols[i] != symbol)
         continue;
      if(when < first[i]) first[i] = when;
      if(when > last[i])  last[i]  = when;
      return;
   }
   int at = ArraySize(symbols);
   ArrayResize(symbols, at + 1);
   ArrayResize(first,   at + 1);
   ArrayResize(last,    at + 1);
   symbols[at] = symbol;
   first[at]   = when;
   last[at]    = when;
}

// One request per symbol, and never in the same request as the deals.
//
// A batch of deals plus two hundred bars for each symbol they touched is a
// large body, and WebRequest fails outright rather than truncating -- the
// deals were being lost along with the candles. Separate requests keep each
// one small, and a failed candle upload costs a chart rather than a trade.
void PostWindows(string &symbols[], datetime &first[], datetime &last[])
{
   for(int i = 0; i < ArraySize(symbols); i++)
   {
      string one = CandlesJson(symbols[i], first[i], last[i]);
      if(StringLen(one) == 0)
         continue;
      string body = "{" + JStr("source", "ea")
                  + ",\"account\":" + AccountJson()
                  + ",\"deals\":[]"
                  + ",\"candles\":[" + one + "]}";
      string reply;
      if(!HttpPost("/mt5/ingest", body, reply))
         Print("TradeZulu: could not send candles for ", symbols[i]);
   }
}

// Walk recent history and send bars for every symbol traded in it, whether or
// not the deals themselves are new. Bounded to CandleBackfillDays so a
// two-year history does not turn into hundreds of requests on startup.
void BackfillCandles(const datetime now)
{
   datetime from = now - (datetime)(86400 * (long)MathMax(1, CandleBackfillDays));
   if(!HistorySelect(from, now + 3600))
      return;

   string   symbols[];
   datetime first[], last[];
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_TYPE) > DEAL_TYPE_SELL)
         continue;
      TrackWindow(symbols, first, last,
                  HistoryDealGetString(ticket, DEAL_SYMBOL),
                  (datetime)HistoryDealGetInteger(ticket, DEAL_TIME));
   }
   if(ArraySize(symbols) > 0)
   {
      Print("TradeZulu: sending chart data for ", ArraySize(symbols), " symbol(s)");
      PostWindows(symbols, first, last);
   }
}

void SendClosedDeals()
{
   if(!g_cursor_known)
   {
      FetchCursor();
      if(!g_cursor_known)
         return;         // server unreachable; try again on the next pass
   }

   datetime now = TimeCurrent();
   datetime from = (g_last_ticket == 0)
                 ? now - (datetime)(86400 * (long)MathMax(1, FirstSyncDays))
                 : now - (datetime)(86400 * 7);   // a week of overlap for late swaps

   if(!HistorySelect(from, now + 3600))
      return;

   int total = HistoryDealsTotal();
   string batch = "";
   int    in_batch = 0;
   ulong  newest = g_last_ticket;

   // One candle window per symbol touched by this batch, rather than per deal:
   // twenty trades on EURUSD in a day want one set of bars, not twenty.
   string   seen_symbols[];
   datetime seen_first[], seen_last[];

   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0 || ticket <= g_last_ticket)
         continue;

      // Deposits and withdrawals are sent too, not filtered out: the server
      // works out the account's starting balance from them.
      batch += (in_batch > 0 ? "," : "") + DealJson(ticket);
      in_batch++;
      if(ticket > newest)
         newest = ticket;

      if(UploadCandles && HistoryDealGetInteger(ticket, DEAL_TYPE) <= DEAL_TYPE_SELL)
         TrackWindow(seen_symbols, seen_first, seen_last,
                     HistoryDealGetString(ticket, DEAL_SYMBOL),
                     (datetime)HistoryDealGetInteger(ticket, DEAL_TIME));

      if(in_batch >= MathMax(20, DealsPerRequest))
      {
         if(!PostDeals(batch))
            return;      // keep the cursor where it was; the batch is retried
         g_sent_deals += in_batch;
         PostWindows(seen_symbols, seen_first, seen_last);
         batch = "";
         in_batch = 0;
         ArrayResize(seen_symbols, 0);
         ArrayResize(seen_first, 0);
         ArrayResize(seen_last, 0);
      }
   }

   if(in_batch > 0)
   {
      if(!PostDeals(batch))
         return;
      g_sent_deals += in_batch;
      PostWindows(seen_symbols, seen_first, seen_last);
   }

   // Only now, once everything is acknowledged. Moving it earlier would skip
   // whatever was in a batch that failed to send.
   g_last_ticket = newest;

   // Charts for trades the journal already has.
   //
   // Candles otherwise only ride along with new deals, so an account whose
   // history was sent before this existed would never get any -- every trade
   // in it would draw an empty chart forever. Done once per run, over a
   // bounded window, because it is a backfill and not a routine.
   if(UploadCandles && !g_candles_done)
   {
      g_candles_done = true;
      BackfillCandles(now);
   }
}

bool HttpPost(const string path, const string body, string &reply)
{
   string url = ServerUrl + path;
   string headers = "Content-Type: application/json\r\nX-API-Key: " + ApiKey + "\r\n";

   char post[];
   char result[];
   string result_headers;

   int len = StringToCharArray(body, post, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(len < 0) len = 0;
   ArrayResize(post, len);

   ResetLastError();
   int status = WebRequest("POST", url, headers, RequestTimeoutMs, post, result, result_headers);
   if(status == -1)
   {
      int error = GetLastError();
      if(error == 4014)
         Print("TradeZulu: WebRequest is not allowed for ", url,
               ". Add it under Tools -> Options -> Expert Advisors.");
      else
         Print("TradeZulu: WebRequest failed for ", url, " (error ", error, ")");
      return false;
   }

   reply = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status < 200 || status >= 300)
   {
      Print("TradeZulu: server returned ", status, " for ", url,
            " body=", StringLen(body), "B reply=", StringSubstr(reply, 0, 200));
      return false;
   }
   return true;
}

void ShowStatus()
{
   Comment(StringFormat(
      "TradeZulu copier\n%s\naccount %I64d on %s\nexecuted %d, failed %d\n"
      "deals sent %d\npolling every %ds",
      g_status,
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoString(ACCOUNT_SERVER),
      g_done, g_failed, g_sent_deals, g_poll_seconds));
}
//+------------------------------------------------------------------+
