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
// A slave holds one request open and the server answers it the moment the
// master moves, so there is no interval between a fill there and a copy here.
// The hold has to outlive the server's own, or the terminal hangs up on the
// answer it was waiting for; 0 turns it off and goes back to asking on a timer.
// Ten rather than longer: while the request is held this terminal is inside
// WebRequest, and its own events -- a manual trade here, a deal to journal --
// are queued until it returns. Copying does not care, because the master's
// move is what ends the hold, but a trade placed by hand on this account waits
// for it. Ten seconds is inside what the journal is allowed to lag.
input int    HoldSeconds     = 10;                             // Keep one request open, waiting for the master (0 = poll instead)

input group "Behaviour"
input int    PollSeconds      = 2;     // How often to report in, in seconds. The server can ask for faster or slower.
input int    Slippage         = 20;    // Maximum deviation, in points
input int    MagicNumber      = 0;     // Stamped on copied orders; 0 leaves it unset
input bool   Verbose          = true;  // Log every command to the Experts tab

input group "Journal"
input bool   SendHistory      = true;  // Send closed deals so the journal fills itself
input int    HistorySeconds   = 60;    // Safety net: how often to look anyway, in case an event was missed
input int    SymbolsSeconds   = 300;   // How often to send the broker's symbol list
input int    FirstSyncDays    = 730;   // How far back to go the first time
input int    DealsPerRequest  = 200;   // Batch size; a long history is sent in pieces
input bool   UploadCandles    = true;  // Send bars around each trade, so charts have something to draw
// M5 rather than M15: everything above it is arithmetic -- the server builds
// M15, M30, H1, H4 and D1 out of these -- while nothing can build M5 out of
// M15. The base timeframe is the only one that has to be collected, so it is
// the smallest one worth storing.
input ENUM_TIMEFRAMES CandleTimeframe = PERIOD_M5;   // Which timeframe to send until the server says (others are derived from it)
// A full trading day either side, so a chart can be zoomed out to the session
// the trade happened in rather than to the twenty bars around the entry. 288
// M5 bars is 24 hours.
input int    CandlesBefore    = 288;   // Bars before the entry (until the server says)
input int    CandlesAfter     = 288;   // Bars after the exit (until the server says)
input int    CandleBackfillDays = 60;  // How far back to fetch charts for trades already journalled
input bool   PlainChart       = true;  // Hide the bars on this chart and show only the status text

//--- state ----------------------------------------------------------
string g_status       = "starting";
string g_pending      = "";   // results waiting to go back on the next poll
int    g_done         = 0;
int    g_failed       = 0;
int    g_poll_seconds = 0;
int    g_poll_ms      = 0;    // what the timer actually runs at
int    g_max_age_ms   = 500;  // how old a command may be before it is refused
int    g_hold_seconds = 0;    // how long the server may keep our request
uint   g_last_history = 0;    // GetTickCount() of the last history send
string g_role         = "";   // master or slave, as the server sees us
bool   g_enabled      = false;// whether this account is armed to copy
uint   g_asked_at     = 0;    // GetTickCount() when the request went out
uint   g_last_poll    = 0;    // GetTickCount() of the last poll, for debouncing

//--- journal --------------------------------------------------------
ulong    g_last_ticket  = 0;      // highest deal the server already has
bool     g_cursor_known = false;
datetime g_next_history = 0;
datetime g_next_symbols = 0;   // the broker's symbol list, sent occasionally
int      g_sent_deals   = 0;
bool     g_candles_done = false;   // the one-off backfill for trades already journalled
// How much chart history to send around each trade, in seconds either side.
// Set in the journal, in days, and sent down on every heartbeat; zero until
// the server has said, when the CandlesBefore/After inputs stand in.
int      g_history_before = 0;
int      g_history_after  = 0;
// Which timeframe to collect, as the length of one bar. Set in the journal and
// sent down on every heartbeat; PERIOD_CURRENT until it has, when the
// CandleTimeframe input stands in.
ENUM_TIMEFRAMES g_candle_tf = PERIOD_CURRENT;

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

   if(PlainChart)
      StyleChart();

   g_poll_seconds = MathMax(1, PollSeconds);
   g_poll_ms      = g_poll_seconds * 1000;
   // Milliseconds, not seconds: copying is a race against the market and the
   // interval is the floor under every copy. The server asks for the rate it
   // wants -- half a second while anything is armed, ten seconds when nothing
   // is -- and this is only the value until the first reply arrives.
   EventSetMillisecondTimer(200);   // first tick promptly, then settle
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
      EventSetMillisecondTimer(g_poll_ms);
   }
   Poll();

   // The journal runs on its own clock. Copying is worth doing every couple of
   // seconds; history is not, and walking it that often would spend the whole
   // timer on deals that have not changed.
   // The safety net. Deals arrive on their own event now, so this is here for
   // what that event cannot catch: a terminal that was closed when the trade
   // closed, or a send that failed while the server was restarting.
   if(SendHistory && TimeCurrent() >= g_next_history)
   {
      g_next_history = TimeCurrent() + (datetime)MathMax(10, HistorySeconds);
      g_last_history = GetTickCount();
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
// Every symbol the broker offers, not only the ones in Market Watch.
//
// Market Watch on a fresh terminal is whatever default the broker ships --
// a handful of majors -- and the journal can only copy onto a symbol it has
// been told exists. A Vantage master trading XAUUSD+ onto a Vantage slave was
// refused with "this broker has no symbol matching XAUUSD+" for no better
// reason than that nobody had opened the symbol on the slave, and an explicit
// mapping did not help because that is checked against the same list.
//
// Trading one is already handled: DoOpen calls SymbolSelect before ordering,
// which is what puts it in Market Watch.
string SymbolsJson()
{
   string out = "";
   int total = SymbolsTotal(false);
   for(int i = 0; i < total && i < 5000; i++)
   {
      string name = SymbolName(i, false);
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
   body += "," + JInt("server_time", (long)TimeCurrent());
   body += "," + JBool("trade_allowed", TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0);
   body += ",\"positions\":" + PositionsJson();
   // A broker's whole symbol list is thousands of entries and changes about
   // never, so it goes at a slow cadence of its own rather than with every
   // heartbeat. The server keeps the last one it was sent.
   if(TimeCurrent() >= g_next_symbols)
   {
      g_next_symbols = TimeCurrent() + (datetime)MathMax(60, SymbolsSeconds);
      body += ",\"symbols\":" + SymbolsJson();
   }
   else
      body += ",\"symbols\":[]";
   body += ",\"results\":[" + g_pending + "]";
   body += "}";
   return body;
}

//--- the heartbeat --------------------------------------------------
void Poll()
{
   g_last_poll = GetTickCount();
   // Everything that follows is measured from here: the round trip, the
   // planning at the other end, and whatever the terminal was busy with in
   // between. A command older than the budget is refused rather than filled.
   g_asked_at = g_last_poll;

   // Held open while this terminal is a slave with copying armed: the server
   // keeps the request until the master reports something worth passing on, so
   // the command arrives on the fill rather than on the next tick of a clock.
   // Everything else -- the master, an idle slave, the journal -- asks and is
   // answered at once.
   string path = "/agent/poll";
   int timeout = RequestTimeoutMs;
   if(g_hold_seconds > 0 && g_role == "slave" && g_enabled)
   {
      path += "?wait=" + IntegerToString(g_hold_seconds);
      // Longer than the hold, or the terminal gives up on the answer it asked
      // to wait for and the server is left talking to nobody.
      timeout = (g_hold_seconds + 10) * 1000;
   }

   string reply;
   if(!HttpPostFor(path, PollBody(), reply, timeout))
   {
      g_status = "server unreachable";
      return;
   }

   // Everything we just reported was accepted, so stop resending it.
   g_pending = "";

   // Milliseconds if the server speaks them, seconds if it is an older one.
   int wanted_ms = (int)StringToInteger(JsonValue(reply, "poll_ms"));
   if(wanted_ms <= 0)
      wanted_ms = (int)StringToInteger(JsonValue(reply, "poll_seconds")) * 1000;
   if(wanted_ms > 0 && wanted_ms != g_poll_ms)
   {
      g_poll_ms = wanted_ms;
      g_poll_seconds = (int)MathMax(1, wanted_ms / 1000);
      EventKillTimer();
      EventSetMillisecondTimer(g_poll_ms);
   }

   // How much chart history the journal wants around each trade. It is a
   // setting there, in days, so widening it reaches every terminal on the next
   // heartbeat instead of waiting for a restart.
   int max_age = (int)StringToInteger(JsonValue(reply, "command_max_age_ms"));
   if(max_age > 0)
      g_max_age_ms = max_age;

   g_history_before = (int)StringToInteger(JsonValue(reply, "history_before_seconds"));
   g_history_after  = (int)StringToInteger(JsonValue(reply, "history_after_seconds"));

   // Which timeframe to collect. Sent as the length of one bar so neither side
   // has to agree with the other about how a timeframe is spelled.
   int bar = (int)StringToInteger(JsonValue(reply, "candle_seconds"));
   if(bar > 0)
      g_candle_tf = TimeframeOf(bar);

   g_role   = JsonValue(reply, "role");
   g_enabled = JsonValue(reply, "enabled") == "true";
   g_hold_seconds = MathMax(0, HoldSeconds);
   bool halted = JsonValue(reply, "halted") == "true";
   g_status = halted ? "halted by the server" : g_role;

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

//| One command's outcome, held until the next poll rather than sent on
//| its own: one round trip instead of two, and a dropped result simply
//| repeats on the following one.
void QueueResult(const string id, const string action, const bool ok,
                 const long ticket, const long master, const string symbol,
                 const string dirn, const double volume, const double price,
                 const int retcode, const string message)
{
   string r = "{" + JStr("id", id) + "," + JStr("action", action);
   r += "," + JBool("ok", ok);
   r += "," + JInt("ticket", ticket);
   r += "," + JInt("master_position_id", master);
   r += "," + JStr("symbol", symbol);
   r += "," + JStr("direction", dirn);
   r += "," + JNum("volume", volume, 2);
   r += "," + JNum("price", price, 8);
   r += "," + JInt("retcode", retcode);
   r += "," + JStr("message", message);
   r += "}";
   if(StringLen(g_pending) > 0)
      g_pending += ",";
   g_pending += r;
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

   // Too late to be this trade any more. A copy is worth having because it is
   // the master's position at the master's price; one placed a second after
   // the fact is a different trade nobody chose, and the terminal is the only
   // place that knows how long it actually took to get here -- the round trip,
   // the planning, and whatever it was busy with in between.
   //
   // Closes are exempt. Being late out of a position is a reason to hurry, not
   // a reason to stay in it.
   uint age = GetTickCount() - g_asked_at;
   if(g_max_age_ms > 0 && (int)age > g_max_age_ms &&
      (action == "open" || action == "modify"))
   {
      string late = StringFormat("refused: %dms old, over the %dms budget",
                                 (int)age, g_max_age_ms);
      Print("TradeZulu: ", late, " -- ", action, " ", symbol);
      QueueResult(id, action, false, 0, master, symbol, dirn, volume, 0.0, 0, late);
      return;
   }

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

   QueueResult(id, action, ok, (long)got_ticket, master, symbol, dirn,
               volume, got_price, retcode, message);
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
   // The broker's own clock. Every other time in this payload -- deal times,
   // candle times -- is on it and carries no offset, so without this one the
   // journal cannot tell 09:00 in Cyprus from 09:00 anywhere else. The server
   // works the offset out by comparing it against real UTC on arrival.
   out += "," + JInt("server_time", (long)TimeCurrent());
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

// The timeframe whose bars last this many seconds. Anything unrecognised
// leaves the collected timeframe alone rather than guessing at a neighbour:
// collecting the wrong one silently is worse than collecting the old one.
ENUM_TIMEFRAMES TimeframeOf(const int bar_seconds)
{
   switch(bar_seconds)
   {
      case 60:     return PERIOD_M1;
      case 300:    return PERIOD_M5;
      case 900:    return PERIOD_M15;
      case 1800:   return PERIOD_M30;
      case 3600:   return PERIOD_H1;
      case 14400:  return PERIOD_H4;
      case 86400:  return PERIOD_D1;
      case 604800: return PERIOD_W1;
   }
   return g_candle_tf;
}

// Which timeframe is actually being collected: what the server asked for, or
// the input until it has asked.
ENUM_TIMEFRAMES CollectedTimeframe()
{
   return g_candle_tf == PERIOD_CURRENT ? CandleTimeframe : g_candle_tf;
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
   ENUM_TIMEFRAMES tf = CollectedTimeframe();
   int span = PeriodSeconds(tf);
   // The server owns this window: it is set in the journal, in days, and sent
   // here on every heartbeat, so widening it takes effect on the next trade
   // rather than at the next restart. The inputs above are what to use until
   // it has said, and for a terminal running without one.
   int before = g_history_before > 0 ? g_history_before : span * MathMax(1, CandlesBefore);
   int after  = g_history_after  > 0 ? g_history_after  : span * MathMax(1, CandlesAfter);
   datetime start = from - (datetime)before;
   datetime end   = to   + (datetime)after;

   int got = CopyRates(symbol, tf, start, end, rates);
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
        + "," + JStr("timeframe", TimeframeName(tf))
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
   return HttpPostFor(path, body, reply, RequestTimeoutMs);
}

bool HttpPostFor(const string path, const string body, string &reply, const int timeout_ms)
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
   int status = WebRequest("POST", url, headers, timeout_ms, post, result, result_headers);
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

//+------------------------------------------------------------------+
//| Make this chart a background for the status text, nothing more.  |
//|                                                                  |
//| The chart the copier sits on is not there to be read. Nobody      |
//| chose its symbol -- the provisioner opens EURUSD H1 because       |
//| something has to hold the expert -- and now that the terminal can |
//| be watched from the web interface, a wall of candles nobody asked |
//| for is the first thing on screen. What is worth reading is the    |
//| comment this EA writes, and that was competing with the bars      |
//| behind it.                                                        |
//|                                                                  |
//| MetaTrader has no "hide the bars" switch, so they are painted in  |
//| the background colour: the drawing still happens and there is     |
//| nothing to see. The green is TradeZulu's own, so a glance at the  |
//| terminal matches a glance at the site.                            |
//+------------------------------------------------------------------+
void StyleChart()
{
   const color background = C'18,176,111';   // --tz-gain, #12b06f
   const color text       = C'255,255,255';

   ChartSetInteger(0, CHART_COLOR_BACKGROUND, background);
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, text);

   // Everything that draws price, in the colour of the thing behind it.
   const int hidden[] = {
      CHART_COLOR_GRID, CHART_COLOR_CHART_UP, CHART_COLOR_CHART_DOWN,
      CHART_COLOR_CHART_LINE, CHART_COLOR_CANDLE_BULL, CHART_COLOR_CANDLE_BEAR,
      CHART_COLOR_VOLUME, CHART_COLOR_BID, CHART_COLOR_ASK, CHART_COLOR_LAST,
      CHART_COLOR_STOP_LEVEL
   };
   for(int i = 0; i < ArraySize(hidden); i++)
      ChartSetInteger(0, (ENUM_CHART_PROPERTY_INTEGER)hidden[i], background);

   // And everything that would draw furniture around them.
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHOW_VOLUMES, CHART_VOLUME_HIDE);
   ChartSetInteger(0, CHART_SHOW_OHLC, false);
   ChartSetInteger(0, CHART_SHOW_BID_LINE, false);
   ChartSetInteger(0, CHART_SHOW_ASK_LINE, false);
   ChartSetInteger(0, CHART_SHOW_LAST_LINE, false);
   ChartSetInteger(0, CHART_SHOW_PERIOD_SEP, false);
   ChartSetInteger(0, CHART_SHOW_OBJECT_DESCR, false);
   ChartSetInteger(0, CHART_SHOW_TRADE_LEVELS, false);
   ChartSetInteger(0, CHART_SHOW_PRICE_SCALE, false);
   ChartSetInteger(0, CHART_SHOW_DATE_SCALE, false);
   // The one-click panel and the symbol watermark would sit on the text.
   ChartSetInteger(0, CHART_SHOW_ONE_CLICK, false);
   ChartSetInteger(0, CHART_FOREGROUND, false);

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| A position opened or closed here: say so now, not on the timer.  |
//|                                                                  |
//| The timer is the floor under every copy -- a slave cannot be told |
//| to open something the server has not heard about, and the server  |
//| hears about it when this terminal next reports. Waiting out the   |
//| interval to mention a trade that has *already happened* is the    |
//| one wait with nothing to gain from it.                            |
//|                                                                  |
//| Debounced, because MetaTrader fires several transactions for one  |
//| trade -- the order, the deal, the position -- and each of them     |
//| would otherwise be its own HTTP request.                          |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(transaction.type != TRADE_TRANSACTION_DEAL_ADD &&
      transaction.type != TRADE_TRANSACTION_POSITION)
      return;

   if(GetTickCount() - g_last_poll < 150)
      return;

   Poll();

   // And the journal, on the same event rather than on its own clock. A deal
   // is the only thing that puts a trade in the journal, so there is nothing
   // to wait for once one has landed: the timer below stays only as a safety
   // net for whatever happened while this terminal was not running.
   if(SendHistory && GetTickCount() - g_last_history >= 250)
   {
      g_last_history = GetTickCount();
      SendClosedDeals();
   }
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
