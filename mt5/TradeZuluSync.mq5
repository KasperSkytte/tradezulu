//+------------------------------------------------------------------+
//|                                              TradeZuluSync.mq5   |
//|  Pushes closed deals from this terminal to a TradeZulu journal.   |
//|                                                                  |
//|  Nothing on the TradeZulu side needs to reach your PC: the        |
//|  terminal makes outbound calls only, authenticated with a shared  |
//|  key. No broker credentials ever leave MetaTrader.                |
//|                                                                  |
//|  Setup                                                           |
//|    1. Copy this file to MQL5/Experts and compile it (F7).        |
//|    2. Tools -> Options -> Expert Advisors -> tick "Allow         |
//|       WebRequest for listed URL" and add your TradeZulu origin,  |
//|       for example https://journal.example.com                     |
//|    3. Drag the EA onto any chart, set ServerUrl and ApiKey.       |
//|                                                                  |
//|  The EA is a reporter, not a trader: it never places an order.    |
//+------------------------------------------------------------------+
#property copyright "TradeZulu"
#property link      "https://github.com/"
#property version   "1.00"
#property strict
#property description "Sends MetaTrader 5 deal history to a TradeZulu trading journal."

//--- inputs ---------------------------------------------------------
input group "Connection"
input string ServerUrl            = "http://192.168.1.10:8420/api"; // TradeZulu API base URL (ends with /api)
input string ApiKey               = "";                             // TZ_INGEST_TOKEN from the server's .env
input int    RequestTimeoutMs     = 15000;                          // WebRequest timeout (ms)

input group "Synchronisation"
input int    SyncIntervalSeconds  = 60;    // How often to look for new deals
input int    FirstSyncHistoryDays = 730;   // How far back to reach on the very first sync
input int    DealsPerRequest      = 300;   // Deals per HTTP request (keeps payloads small)
input bool   SyncOnTrade          = true;  // Also sync immediately when a position closes

input group "Charts"
input bool             UploadCandles   = true;        // Send candles so trades can be replayed offline
input ENUM_TIMEFRAMES  CandleTimeframe = PERIOD_M15;  // Timeframe to upload
input int              CandlesBefore   = 150;         // Bars before the first entry
input int              CandlesAfter    = 80;          // Bars after the last exit

input group "Diagnostics"
input bool   Verbose = true;   // Log every request to the Experts tab

//--- state ----------------------------------------------------------
datetime g_last_sync_time   = 0;      // newest deal time the server confirmed
ulong    g_last_sync_ticket = 0;      // newest deal ticket the server confirmed
bool     g_cursor_known     = false;
string   g_status           = "starting";
int      g_total_sent       = 0;
int      g_failures         = 0;

// Remembered stop/target per position. MetaTrader only stores the stop loss
// on the *order*, so a stop attached after entry would otherwise be lost by
// the time the position closes. We snapshot it the first time we see the
// position open, and keep it across restarts in MQL5/Files.
ulong    g_pos_id[];
double   g_pos_sl[];
double   g_pos_tp[];

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

   LoadStopCache();
   SnapshotOpenPositions();

   // Do not block OnInit with network traffic: the first timer tick, one
   // second from now, does the initial sync and then slows to the interval.
   EventSetTimer(1);
   Print("TradeZulu: started, target ", ServerUrl);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   SaveStopCache();
   Comment("");
   Print("TradeZulu: stopped (reason ", reason, ")");
}

//+------------------------------------------------------------------+
void OnTimer()
{
   static bool first = true;
   if(first)
   {
      first = false;
      EventKillTimer();
      EventSetTimer(MathMax(10, SyncIntervalSeconds));
   }

   SnapshotOpenPositions();
   Sync(false);
   ShowStatus();
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   // Capture the stop as early as possible, before it can be moved.
   if(trans.type == TRADE_TRANSACTION_POSITION || trans.type == TRADE_TRANSACTION_DEAL_ADD)
      SnapshotOpenPositions();

   if(SyncOnTrade && trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      SnapshotOpenPositions();
      Sync(false);
      ShowStatus();
   }
}

//+------------------------------------------------------------------+
//| Stop/target cache                                                |
//+------------------------------------------------------------------+
string CacheFileName()
{
   return StringFormat("TradeZulu_stops_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN));
}

int FindPosition(const ulong position_id)
{
   for(int i = ArraySize(g_pos_id) - 1; i >= 0; i--)
      if(g_pos_id[i] == position_id)
         return i;
   return -1;
}

void RememberPosition(const ulong position_id, const double sl, const double tp)
{
   int index = FindPosition(position_id);
   if(index >= 0)
   {
      // Only fill in gaps; the *initial* values are the interesting ones.
      if(g_pos_sl[index] == 0.0 && sl > 0.0) g_pos_sl[index] = sl;
      if(g_pos_tp[index] == 0.0 && tp > 0.0) g_pos_tp[index] = tp;
      return;
   }

   int size = ArraySize(g_pos_id);
   ArrayResize(g_pos_id, size + 1);
   ArrayResize(g_pos_sl, size + 1);
   ArrayResize(g_pos_tp, size + 1);
   g_pos_id[size] = position_id;
   g_pos_sl[size] = sl;
   g_pos_tp[size] = tp;
   SaveStopCache();
}

void SnapshotOpenPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      RememberPosition(PositionGetInteger(POSITION_IDENTIFIER),
                       PositionGetDouble(POSITION_SL),
                       PositionGetDouble(POSITION_TP));
   }
}

void LoadStopCache()
{
   ArrayResize(g_pos_id, 0);
   ArrayResize(g_pos_sl, 0);
   ArrayResize(g_pos_tp, 0);

   int handle = FileOpen(CacheFileName(), FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return;

   while(!FileIsEnding(handle))
   {
      string id = FileReadString(handle);
      if(StringLen(id) == 0)
         break;
      string sl = FileReadString(handle);
      string tp = FileReadString(handle);

      int size = ArraySize(g_pos_id);
      ArrayResize(g_pos_id, size + 1);
      ArrayResize(g_pos_sl, size + 1);
      ArrayResize(g_pos_tp, size + 1);
      g_pos_id[size] = (ulong)StringToInteger(id);
      g_pos_sl[size] = StringToDouble(sl);
      g_pos_tp[size] = StringToDouble(tp);
   }
   FileClose(handle);
   if(Verbose)
      Print("TradeZulu: remembered stops for ", ArraySize(g_pos_id), " position(s)");
}

void SaveStopCache()
{
   int handle = FileOpen(CacheFileName(), FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
      return;
   for(int i = 0; i < ArraySize(g_pos_id); i++)
      FileWrite(handle, (string)g_pos_id[i],
                DoubleToString(g_pos_sl[i], 8),
                DoubleToString(g_pos_tp[i], 8));
   FileClose(handle);
}

//+------------------------------------------------------------------+
//| JSON helpers                                                     |
//+------------------------------------------------------------------+
string JsonEscape(string text)
{
   StringReplace(text, "\\", "\\\\");
   StringReplace(text, "\"", "\\\"");
   StringReplace(text, "\n", " ");
   StringReplace(text, "\r", " ");
   StringReplace(text, "\t", " ");
   return text;
}

string JsonString(const string key, const string value)
{
   return StringFormat("\"%s\":\"%s\"", key, JsonEscape(value));
}

string JsonNumber(const string key, const double value, const int digits = 8)
{
   return StringFormat("\"%s\":%s", key, DoubleToString(value, digits));
}

string JsonInt(const string key, const long value)
{
   return StringFormat("\"%s\":%I64d", key, value);
}

string AccountJson()
{
   string parts[8];
   parts[0] = JsonString("login",    (string)AccountInfoInteger(ACCOUNT_LOGIN));
   parts[1] = JsonString("name",     AccountInfoString(ACCOUNT_NAME));
   parts[2] = JsonString("server",   AccountInfoString(ACCOUNT_SERVER));
   parts[3] = JsonString("company",  AccountInfoString(ACCOUNT_COMPANY));
   parts[4] = JsonString("currency", AccountInfoString(ACCOUNT_CURRENCY));
   parts[5] = JsonInt("leverage",    AccountInfoInteger(ACCOUNT_LEVERAGE));
   parts[6] = JsonNumber("balance",  AccountInfoDouble(ACCOUNT_BALANCE), 2);
   parts[7] = JsonNumber("equity",   AccountInfoDouble(ACCOUNT_EQUITY), 2);

   string out = "{";
   for(int i = 0; i < ArraySize(parts); i++)
      out += (i > 0 ? "," : "") + parts[i];
   return out + "}";
}

//| Money value of one whole price unit, for one lot.                |
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
   ulong  position_id  = (ulong)HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);
   long   entry        = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);

   // Prefer the stop that was on the entry order; fall back to what we saw on
   // the live position, which covers stops attached after entry.
   double sl = 0.0, tp = 0.0;
   if(entry == DEAL_ENTRY_IN)
   {
      // The order is already in the cache from HistorySelect(); calling
      // HistoryOrderSelect() here would discard the deal list we are walking.
      if(order_ticket > 0)
      {
         sl = HistoryOrderGetDouble(order_ticket, ORDER_SL);
         tp = HistoryOrderGetDouble(order_ticket, ORDER_TP);
      }
      int cached = FindPosition(position_id);
      if(cached >= 0)
      {
         if(sl == 0.0) sl = g_pos_sl[cached];
         if(tp == 0.0) tp = g_pos_tp[cached];
      }
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   string out = "{";
   out += JsonInt("ticket",      (long)deal_ticket);
   out += "," + JsonInt("order", (long)order_ticket);
   out += "," + JsonInt("position_id", (long)position_id);
   out += "," + JsonString("symbol", symbol);
   out += "," + JsonInt("type",  HistoryDealGetInteger(deal_ticket, DEAL_TYPE));
   out += "," + JsonInt("entry", entry);
   out += "," + JsonNumber("volume", HistoryDealGetDouble(deal_ticket, DEAL_VOLUME), 2);
   out += "," + JsonNumber("price",  HistoryDealGetDouble(deal_ticket, DEAL_PRICE), digits);
   out += "," + JsonNumber("profit", HistoryDealGetDouble(deal_ticket, DEAL_PROFIT), 2);
   out += "," + JsonNumber("commission", HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION), 2);
   out += "," + JsonNumber("swap", HistoryDealGetDouble(deal_ticket, DEAL_SWAP), 2);
   out += "," + JsonNumber("fee",  HistoryDealGetDouble(deal_ticket, DEAL_FEE), 2);
   out += "," + JsonNumber("sl", sl, digits);
   out += "," + JsonNumber("tp", tp, digits);
   out += "," + JsonInt("magic", HistoryDealGetInteger(deal_ticket, DEAL_MAGIC));
   out += "," + JsonString("comment", HistoryDealGetString(deal_ticket, DEAL_COMMENT));
   out += "," + JsonInt("time", (long)HistoryDealGetInteger(deal_ticket, DEAL_TIME));
   out += "," + JsonNumber("value_per_unit", ValuePerUnit(symbol), 6);
   out += "," + JsonInt("digits", digits);
   out += "}";
   return out;
}

//+------------------------------------------------------------------+
//| Candles                                                          |
//+------------------------------------------------------------------+
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
      default:         return "M15";
   }
}

string CandleBatchJson(const string symbol, const datetime from, const datetime to)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   int period_seconds = PeriodSeconds(CandleTimeframe);
   datetime start = from - (datetime)(period_seconds * MathMax(0, CandlesBefore));
   datetime stop  = to + (datetime)(period_seconds * MathMax(0, CandlesAfter));
   if(stop > TimeCurrent())
      stop = TimeCurrent();

   int copied = CopyRates(symbol, CandleTimeframe, start, stop, rates);
   if(copied <= 0)
      return "";

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   string out = "{" + JsonString("symbol", symbol) + ","
              + JsonString("timeframe", TimeframeName(CandleTimeframe)) + ",\"candles\":[";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         out += ",";
      out += "{" + JsonInt("time", (long)rates[i].time)
           + "," + JsonNumber("open",  rates[i].open,  digits)
           + "," + JsonNumber("high",  rates[i].high,  digits)
           + "," + JsonNumber("low",   rates[i].low,   digits)
           + "," + JsonNumber("close", rates[i].close, digits)
           + "," + JsonNumber("volume", (double)rates[i].tick_volume, 0)
           + "}";
   }
   return out + "]}";
}

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
bool HttpJson(const string method, const string path, const string body, string &response)
{
   string url     = ServerUrl + path;
   string headers = "Content-Type: application/json\r\nX-API-Key: " + ApiKey + "\r\n";

   char post[], result[];
   string result_headers;

   if(StringLen(body) > 0)
   {
      int length = StringToCharArray(body, post, 0, StringLen(body), CP_UTF8);
      // StringToCharArray appends a terminating zero that must not be sent.
      if(length > 0)
         ArrayResize(post, length - 1);
   }

   ResetLastError();
   int status = WebRequest(method, url, headers, RequestTimeoutMs, post, result, result_headers);

   if(status == -1)
   {
      int error = GetLastError();
      if(error == 4014)
         Print("TradeZulu: WebRequest is not allowed for ", url,
               ". Add the host under Tools -> Options -> Expert Advisors.");
      else
         Print("TradeZulu: WebRequest failed for ", url, " (error ", error, ")");
      g_failures++;
      g_status = "connection error " + (string)error;
      return false;
   }

   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);

   if(status < 200 || status >= 300)
   {
      Print("TradeZulu: HTTP ", status, " from ", url, " -> ", StringSubstr(response, 0, 300));
      g_failures++;
      g_status = "HTTP " + (string)status;
      return false;
   }
   return true;
}

//| Minimal extractor for the couple of numbers we read back.        |
long JsonPickLong(const string json, const string key, const long fallback)
{
   string needle = "\"" + key + "\":";
   int at = StringFind(json, needle);
   if(at < 0)
      return fallback;

   at += StringLen(needle);
   string digits = "";
   for(int i = at; i < StringLen(json); i++)
   {
      ushort c = StringGetCharacter(json, i);
      if((c >= '0' && c <= '9') || (StringLen(digits) == 0 && c == '-'))
         digits += ShortToString(c);
      else if(StringLen(digits) > 0)
         break;
      else if(c != ' ')
         break;
   }
   if(StringLen(digits) == 0)
      return fallback;
   return StringToInteger(digits);
}

//+------------------------------------------------------------------+
//| Synchronisation                                                  |
//+------------------------------------------------------------------+
void FetchCursor()
{
   string response;
   string path = "/mt5/cursor?login=" + (string)AccountInfoInteger(ACCOUNT_LOGIN);
   if(!HttpJson("GET", path, "", response))
      return;

   g_last_sync_ticket = (ulong)JsonPickLong(response, "last_deal_ticket", 0);
   g_cursor_known = true;
   if(Verbose)
      Print("TradeZulu: server already has deals up to ticket ", g_last_sync_ticket);
}

void Sync(const bool force_full)
{
   if(!g_cursor_known)
      FetchCursor();

   datetime now = TimeCurrent();
   datetime from;
   if(force_full || g_last_sync_ticket == 0)
      from = now - (datetime)(86400 * (long)MathMax(1, FirstSyncHistoryDays));
   else if(g_last_sync_time > 0)
      from = g_last_sync_time - 86400;   // overlap a day so late swaps are caught
   else
      from = now - (datetime)(86400 * 30);

   if(!HistorySelect(from, now + 3600))
   {
      Print("TradeZulu: HistorySelect failed");
      return;
   }

   int total = HistoryDealsTotal();
   if(total <= 0)
   {
      g_status = "no history in window";
      return;
   }

   string batch = "";
   int    in_batch = 0;
   int    sent = 0;
   ulong  newest_ticket = g_last_sync_ticket;
   datetime newest_time = g_last_sync_time;

   // Candle windows, one per symbol touched by this batch.
   string   symbols[];
   datetime first_seen[], last_seen[];

   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0 || ticket <= g_last_sync_ticket)
         continue;

      long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
      long entry     = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      datetime when  = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      // Balance, credit and correction records are still worth sending: the
      // server uses them to work out the account's starting balance.
      batch += (in_batch > 0 ? "," : "") + DealJson(ticket);
      in_batch++;

      if(ticket > newest_ticket) newest_ticket = ticket;
      if(when > newest_time)     newest_time = when;

      if(UploadCandles && deal_type <= DEAL_TYPE_SELL)
         TrackSymbolWindow(symbols, first_seen, last_seen,
                           HistoryDealGetString(ticket, DEAL_SYMBOL), when);

      if(in_batch >= MathMax(20, DealsPerRequest))
      {
         if(!PostBatch(batch, symbols, first_seen, last_seen))
            return;
         sent += in_batch;
         batch = "";
         in_batch = 0;
         ArrayResize(symbols, 0);
         ArrayResize(first_seen, 0);
         ArrayResize(last_seen, 0);
      }
   }

   if(in_batch > 0)
   {
      if(!PostBatch(batch, symbols, first_seen, last_seen))
         return;
      sent += in_batch;
   }

   g_last_sync_ticket = newest_ticket;
   g_last_sync_time   = newest_time;
   g_total_sent      += sent;

   if(sent > 0)
   {
      PruneStopCache();
      Print("TradeZulu: sent ", sent, " deal(s)");
      g_status = StringFormat("synced %d deal(s) at %s", sent,
                              TimeToString(TimeLocal(), TIME_MINUTES | TIME_SECONDS));
   }
   else
   {
      g_status = "up to date at " + TimeToString(TimeLocal(), TIME_MINUTES | TIME_SECONDS);
   }
}

void TrackSymbolWindow(string &symbols[], datetime &first_seen[], datetime &last_seen[],
                       const string symbol, const datetime when)
{
   if(StringLen(symbol) == 0)
      return;
   for(int i = 0; i < ArraySize(symbols); i++)
   {
      if(symbols[i] == symbol)
      {
         if(when < first_seen[i]) first_seen[i] = when;
         if(when > last_seen[i])  last_seen[i]  = when;
         return;
      }
   }
   int size = ArraySize(symbols);
   ArrayResize(symbols, size + 1);
   ArrayResize(first_seen, size + 1);
   ArrayResize(last_seen, size + 1);
   symbols[size]    = symbol;
   first_seen[size] = when;
   last_seen[size]  = when;
}

bool PostBatch(const string deals_json, string &symbols[],
               datetime &first_seen[], datetime &last_seen[])
{
   string payload = "{\"account\":" + AccountJson() + ",\"deals\":[" + deals_json + "]";

   if(UploadCandles && ArraySize(symbols) > 0)
   {
      string candles = "";
      for(int i = 0; i < ArraySize(symbols); i++)
      {
         string batch = CandleBatchJson(symbols[i], first_seen[i], last_seen[i]);
         if(StringLen(batch) == 0)
            continue;
         candles += (StringLen(candles) > 0 ? "," : "") + batch;
      }
      if(StringLen(candles) > 0)
         payload += ",\"candles\":[" + candles + "]";
   }
   payload += "}";

   string response;
   if(!HttpJson("POST", "/mt5/ingest", payload, response))
      return false;

   if(Verbose)
      Print("TradeZulu: ", StringSubstr(response, 0, 200));
   return true;
}

//| Drop remembered stops for positions that are closed and reported. |
void PruneStopCache()
{
   ulong  keep_id[];
   double keep_sl[], keep_tp[];

   for(int i = 0; i < ArraySize(g_pos_id); i++)
   {
      bool still_open = false;
      for(int p = PositionsTotal() - 1; p >= 0; p--)
      {
         if(PositionGetTicket(p) == 0)
            continue;
         if((ulong)PositionGetInteger(POSITION_IDENTIFIER) == g_pos_id[i])
         {
            still_open = true;
            break;
         }
      }
      if(!still_open)
         continue;

      int size = ArraySize(keep_id);
      ArrayResize(keep_id, size + 1);
      ArrayResize(keep_sl, size + 1);
      ArrayResize(keep_tp, size + 1);
      keep_id[size] = g_pos_id[i];
      keep_sl[size] = g_pos_sl[i];
      keep_tp[size] = g_pos_tp[i];
   }

   ArrayFree(g_pos_id);
   ArrayFree(g_pos_sl);
   ArrayFree(g_pos_tp);
   ArrayCopy(g_pos_id, keep_id);
   ArrayCopy(g_pos_sl, keep_sl);
   ArrayCopy(g_pos_tp, keep_tp);
   SaveStopCache();
}

//+------------------------------------------------------------------+
void ShowStatus()
{
   Comment(StringFormat(
      "TradeZulu\n"
      "  account : %I64d (%s)\n"
      "  server  : %s\n"
      "  status  : %s\n"
      "  sent    : %d deal(s), %d failure(s)\n"
      "  watching: %d open position(s)",
      AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_CURRENCY),
      ServerUrl, g_status, g_total_sent, g_failures, ArraySize(g_pos_id)));
}
//+------------------------------------------------------------------+
