/* ============================================================================
 *  吃药提醒 + 树莓派串口通信  合并版          开发板：Arduino UNO R3
 * ============================================================================
 *  本文件在保留两部分既有功能的基础上合并整理：
 *    · MedicineReminder.ino  定时吃药提醒（OLED / RTC / 按键 / LED / 语音）
 *    · SerialComm.ino        树莓派串口对接（ASCII 文本行协议 + 语音播报）
 *
 *  【功能一】定时吃药提醒
 *    1. OLED 大字体实时显示 RTC 真实时间 "HH:MM"
 *    2. 一天三个提醒点，到点自动提醒（灯亮 5 秒 + 语音播报）：
 *         08:00 -> D3 亮 5 秒 + 播 001.mp3
 *         14:00 -> D4 亮 5 秒 + 播 002.mp3
 *         20:00 -> D2 亮 5 秒 + 播 003.mp3
 *    3. 按键：A3 进入设置 / A2 退出设置 / A1 时间+1 / A0 时间-1
 *    4. 手动测试：设置模式下【同时按住 A1 + A0】->
 *                 模拟一次 08:00 提醒（D3 亮 5 秒 + 播 001.mp3）
 *
 *  【功能二】树莓派串口通信（协议见《R3串口通信对接说明.md》）
 *    · 9600 / 8N1 / 无流控
 *    · 树莓派 -> R3：ASCII 文本行，4 位数字 + '\n'，如 "0005\n"，兼容忽略 '\r'
 *    · R3 -> 树莓派：有效指令回 "ACK\n"，未知指令回 "ERR\n"
 *    · 无校验和、无包头、无长度、无重传、无心跳
 *    · 指令进入播放队列后立即回复 ACK，不等待音频播放结束
 *    · 树莓派端 ACK 等待时间为 2.0 秒，用于覆盖 MP3 调用造成的短时阻塞
 *
 * ---------------------------------------------------------------------------
 *  【接线一览】
 *    D0          -> 树莓派 TXD      （硬件串口 RX，需分压，见下文警告）
 *    D1          -> 树莓派 RXD      （硬件串口 TX）
 *    D2          -> 晚上灯（20:00 触发，串 220Ω 限流电阻 -> GND）
 *    D3          -> 早上灯（08:00 触发，串 220Ω 限流电阻 -> GND）
 *    D4          -> 中午灯（14:00 触发，串 220Ω 限流电阻 -> GND）
 *    D5          -> OLED SCL        （软件 I2C）
 *    D6          -> OLED SDA        （软件 I2C）
 *    D9          -> MP3 模块 T      （Arduino 软串口 RX / 接收端）
 *    D11         -> MP3 模块 R      （Arduino 软串口 TX / 发送端）
 *    A0~A3       -> 按键（另一端接 GND，按下为低电平）
 *    A4          -> 时钟模块 SDA    （硬件 I2C）
 *    A5          -> 时钟模块 SCL    （硬件 I2C）
 *
 *    MP3 模块：HS-S49A-PL（GD5800 芯片），VCC->5V，GND 共地，喇叭接 SPK_1/SPK_2，
 *              模块 R 脚建议串 1kΩ 电阻再接 D11（GD5800 的 RX 不完全耐 5V）
 *
 *  【依赖库】
 *    - U8g2          (olikraus)    驱动 SSD1306 OLED      —— 需安装
 *    - RTClib        (Adafruit)    驱动 DS3231 / DS1307   —— 需安装
 *    - GD5800_Serial (hznupeter)   驱动 GD5800 语音模块   —— 需安装
 *
 * ---------------------------------------------------------------------------
 *  【⚠️ 三个必须知道的坑】
 *   1) D0/D1 同时连着 USB 转串口芯片。烧录程序时必须【拔掉树莓派的 TX 线】，
 *      否则树莓派和 USB 芯片会同时驱动 Uno 的 RX，导致下载失败。
 *   2) 树莓派 GPIO 是 3.3V 且【不耐 5V】，而 Uno 的 D1 输出 5V。
 *      D1 -> 树莓派 RXD 这条线必须分压（例如 1k 串联 + 2k 下拉，中点接 RXD），
 *      否则可能烧坏树莓派。反方向（3.3V -> D0）一般可以直连。
 *   3) 全系统必须共地。
 *
 * ---------------------------------------------------------------------------
 *  【⚠️ 关于调试打印 DEBUG_SERIAL】
 *    本程序用硬件串口 Serial(D0/D1) 跟树莓派通信，所以所有调试打印
 *    （[TIME] / [ALARM] / [KEY] / RX: / TX: 等）都会【一并发给树莓派】。
 *    树莓派端的解析程序必须只认整行等于 ACK / ERR，其余一律忽略。
 *    正式联调建议保持 DEBUG_SERIAL = 0，避免诊断文本与 ACK/ERR 共用串口。
 *
 * ---------------------------------------------------------------------------
 *  【⚠️ 运行时响应说明】
 *    loop() 内没有主动 delay()，但 MP3 播放调用
 *    GD5800_Serial::playFileByIndexNumber() —— 它内部有
 *    waitUntilAvailable(1000) + 150ms 排空，会阻塞约 0.17~1.2 秒。
 *    仍可能短时阻塞按键扫描、OLED 刷新和串口处理。
 *    吃药提醒每天只触发 3 次；树莓派指令按文档场景每次 2~3 条，
 *    影响可接受。忙碌期间树莓派发来的字节由硬件串口的 64 字节缓冲兜住。
 * ===========================================================================*/

/* ===========================================================================
 * 一、用户配置区
 * ===========================================================================*/

/* ---- 调试打印：1 = 开（会发给树莓派），0 = 关 ---- */
#define DEBUG_SERIAL       0

/* 时钟来源：
 *   1 = 外部 RTC 硬件时钟（当前使用）—— 显示真实时间
 *   0 = 内部软件时钟 —— 上电从 07:59 开始，每 60 秒 +1 分钟
 * 选 1 但模块初始化失败时会自动回退到软件时钟，不会整个程序不工作。 */
#define TIME_SOURCE 1

/* MP3 语音播报：1 = 启用；0 = 禁用（相关代码不参与编译） */
#define USE_MP3 1

/* ---- MP3 曲目编号 ----
 * 填的是模块内部存储里音频的【索引号】，不是文件名。
 * 文件按 001.mp3 ~ 011.mp3 的顺序拷贝时，索引 1~11 正好对应。 */
#define MP3_TRACK_MORNING  1     /* 吃药提醒：早上八点 -> 001.mp3 */
#define MP3_TRACK_NOON     2     /* 吃药提醒：下午两点 -> 002.mp3 */
#define MP3_TRACK_EVENING  3     /* 吃药提醒：晚上八点 -> 003.mp3 */

#define MP3_BAUD           9600  /* GD5800 默认波特率 */
#define MP3_VOLUME         30    /* 音量 0~30（原 MedicineReminder 用 20，这里取 30 更响） */
#define MP3_POWER_ON_MS    1500UL/* 上电后等模块初始化，期间不发指令 */

/* 上电自检：1 = 上电后自动播一次 001.mp3；0 = 关闭
 * （原 MedicineReminder 已设为 0，这里保持一致） */
#define USE_BOOT_TEST      0

/* 设置模式下是否暂停自动走时：1 = 暂停；0 = 不暂停 */
#define PAUSE_TICK_IN_SET_MODE 0

/* RTC 芯片型号：1 = DS3231；0 = DS1307 */
#define RTC_IS_DS3231 1

/* LED 极性：1 = 共阴（输出 HIGH 点亮）；0 = 共阳（输出 LOW 点亮） */
#define LED_ACTIVE_HIGH 1

/* 按键消抖时间 */
#define DEBOUNCE_MS    30UL

/* 按键触发时机：0 = 按下就触发（默认）；1 = 松手才触发 */
#define KEY_TRIGGER_ON_RELEASE 0

/* 长按连续加减：1 = 开启；0 = 关闭（只影响 A1/A0 两个键） */
#define ENABLE_LONG_PRESS_REPEAT 1
#define LONG_PRESS_MS          500UL  /* 按住多久开始连发 */
#define LONG_PRESS_REPEAT_MS   120UL  /* 连发间隔 */

/* ---- 时间常量 ---- */
#define START_HOUR     7      /* 开机起始时间：07:59（演示/回退用） */
#define START_MINUTE   59

#define MORNING_HOUR   8      /* 早上：08:00 */
#define MORNING_MINUTE 0
#define NOON_HOUR      14     /* 中午：14:00 */
#define NOON_MINUTE    0
#define EVENING_HOUR   20     /* 晚上：20:00 */
#define EVENING_MINUTE 0

#define LED_ON_MS      5000UL /* 灯亮时长：5 秒 */

/* ---- 树莓派协议相关 ---- */

/* 指令范围：文档规定 0001~0011 */
#define CMD_MIN            1
#define CMD_MAX            11

/* 模块内部存储里实际有几个音频文件（001.mp3 ~ 011.mp3 共 11 个） */
#define MP3_FILE_COUNT     11

/* 播放队列深度：文档要求"至少 3 条"，这里给足冗余 */
#define QUEUE_SIZE         8

/* 接收超时：开始收数字后，超过这么久没等到 '\n' 就丢弃重来 */
#define CMD_TIMEOUT_MS     500UL

/* 格式错误的行（如 "abc\n"、"00123\n"）是否回 ERR
 *   0 = 静默忽略（默认，避免杂讯刷屏）
 *   1 = 回 "ERR\n" */
#define MALFORMED_REPLY_ERR 0

/* ===========================================================================
 * 二、引脚定义（两份原文件统一后的结果）
 * ===========================================================================*/

/* 按键引脚 */
const uint8_t PIN_KEY_MINUS = A0;  /* 时间 -1 分钟（仅设置模式） */
const uint8_t PIN_KEY_PLUS  = A1;  /* 时间 +1 分钟（仅设置模式） */
const uint8_t PIN_KEY_EXIT  = A2;  /* 退出设置模式 */
const uint8_t PIN_KEY_SET   = A3;  /* 进入设置模式 */

/* 灯：D3 早 / D4 中 / D2 晚 */
const uint8_t PIN_LED_MORNING = 3;
const uint8_t PIN_LED_NOON    = 4;
const uint8_t PIN_LED_EVENING = 2;

/* OLED：软件 I2C（A4/A5 已被 RTC 占用） */
const uint8_t PIN_OLED_SCL = 5;
const uint8_t PIN_OLED_SDA = 6;

/* MP3 软件串口
 *   PIN_MP3_RX = Arduino 接收脚，接 MP3 模块的 T  -> D9
 *   PIN_MP3_TX = Arduino 发送脚，接 MP3 模块的 R  -> D11
 * 没声音就把这两个值对调（改成 11 和 9）再试一次。 */
const uint8_t PIN_MP3_RX = 9;
const uint8_t PIN_MP3_TX = 11;

/* 树莓派走硬件串口 D0(RX) / D1(TX)，不需要 pinMode 定义 */

/* LED 实际输出电平：由 LED_ACTIVE_HIGH 推导，代码里统一用 ledOn()/ledOff() */
#if LED_ACTIVE_HIGH
  #define LED_ON_LEVEL  HIGH
  #define LED_OFF_LEVEL LOW
#else
  #define LED_ON_LEVEL  LOW
  #define LED_OFF_LEVEL HIGH
#endif

/* ===========================================================================
 * 三、头文件
 * ===========================================================================*/

#include <Wire.h>
#include <U8g2lib.h>
#include <RTClib.h>
#if USE_MP3
#include <GD5800_Serial.h>
#endif

/* ===========================================================================
 * 四、全局对象
 * ===========================================================================*/

/* OLED：SSD1306 128x64，软件 I2C
 * 用 _1_ 页缓冲模式（只占 128 字节 RAM），必须用 firstPage()/nextPage() 画屏 */
U8G2_SSD1306_128X64_NONAME_1_SW_I2C u8g2(U8G2_R0, /* clock=*/ PIN_OLED_SCL,
                                          /* data=*/ PIN_OLED_SDA,
                                          /* reset=*/ U8X8_PIN_NONE);

/* RTC 时钟模块：走硬件 I2C（A4=SDA, A5=SCL） */
#if RTC_IS_DS3231
RTC_DS3231 rtc;
#else
RTC_DS1307 rtc;
#endif

#if USE_MP3
/* MP3 语音模块：HS-S49A-PL（GD5800 芯片）
 * 构造函数参数顺序是 (RX, TX)：D9 接收、D11 发送 */
GD5800_Serial mp356(PIN_MP3_RX, PIN_MP3_TX);
#endif

/* ---- 调试打印宏（DEBUG_SERIAL = 0 时整条语句被编译器丢弃）----
 * 注意：这些打印走的是跟树莓派同一条串口，树莓派端必须能忽略它们 */
#if DEBUG_SERIAL
  #define DBG_PRINT(x)    Serial.print(x)
  #define DBG_PRINTLN(x)  Serial.println(x)
#else
  #define DBG_PRINT(x)    do {} while (0)
  #define DBG_PRINTLN(x)  do {} while (0)
#endif

/* ===========================================================================
 * 五、按键状态机定义
 * ===========================================================================*/

enum KeyEvent {
  KEY_EVENT_NONE = 0,   /* 无事件 */
  KEY_EVENT_CLICK,      /* 一次有效按键 */
  KEY_EVENT_REPEAT      /* 长按连发 */
};

enum KeyState {
  KS_IDLE = 0,          /* 空闲，等待一次"稳定按下" */
  KS_PRESSED            /* 已确认按下 */
};

struct Key {
  uint8_t       pin;            /* 引脚号 */
  const char   *name;           /* 串口调试名，如 "A0" */
  KeyState      state;          /* 状态机当前状态 */
  bool          raw;            /* 最近一次原始读数（true = 按下） */
  bool          lastStable;     /* 上一次稳定电平（true = 按下） */
  bool          repeatEnabled;  /* 是否支持长按连发 */
  unsigned long tChange;        /* 原始电平变化时刻（消抖计时） */
  unsigned long tPress;         /* 确认按下的时刻（长按计时起点） */
  unsigned long tRepeat;        /* 上次连发触发的时刻 */
};

/* ===========================================================================
 * 六、状态变量
 * ===========================================================================*/

/* ---- 时间与设置模式 ---- */
int  curHour   = START_HOUR;
int  curMinute = START_MINUTE;
bool setMode   = false;

bool rtcOk = false;                /* RTC 是否可用（失败自动回退软件时钟） */

unsigned long lastMinuteTick = 0;  /* 软件时钟走时基准 */
int lastMinuteOfDay = -1;          /* 上一次的"当日第几分钟"，用于边沿检测 */

/* ---- 三盏灯的状态与起始时刻 ---- */
bool          morningLedActive  = false;
unsigned long morningLedStart   = 0;
bool          noonLedActive     = false;
unsigned long noonLedStart      = 0;
bool          eveningLedActive  = false;
unsigned long eveningLedStart   = 0;

unsigned long lastDraw = 0;        /* 上次刷新 OLED 的时刻 */

Key keyMinus = { PIN_KEY_MINUS, "A0", KS_IDLE, false, false,
                 (bool)ENABLE_LONG_PRESS_REPEAT, 0, 0, 0 };
Key keyPlus  = { PIN_KEY_PLUS,  "A1", KS_IDLE, false, false,
                 (bool)ENABLE_LONG_PRESS_REPEAT, 0, 0, 0 };
Key keyExit  = { PIN_KEY_EXIT,  "A2", KS_IDLE, false, false, false, 0, 0, 0 };
Key keySet   = { PIN_KEY_SET,   "A3", KS_IDLE, false, false, false, 0, 0, 0 };

/* ---- MP3 播放队列（环形缓冲，FIFO）----
 * 定时提醒、手动测试、树莓派指令 三个来源都入同一个队列，统一排队播放。
 * 这样"谁触发的"不影响播放逻辑，也天然保证不会两条音频叠在一起。 */
#if USE_MP3
uint8_t queueBuf[QUEUE_SIZE];
uint8_t queueHead  = 0;            /* 出队位置 */
uint8_t queueTail  = 0;            /* 入队位置 */
uint8_t queueCount = 0;            /* 当前排队条数 */

bool          isPlaying   = false; /* 是否有一曲正在播 */
uint8_t       curTrack    = 0;     /* 当前播放的曲目号 */
unsigned long playStartMs = 0;     /* 当前曲目开始播放的时刻 */
unsigned long curTrackMs  = 0;     /* 当前曲目预估时长（查表得到） */
#endif

/* ---- 树莓派指令解析状态机 ---- */
enum PiState {
  PI_WAIT_DIGIT = 0,   /* 等待第一个数字 */
  PI_IN_DIGITS         /* 正在收 4 位数字 */
};

PiState       piState      = PI_WAIT_DIGIT;
char          piDigits[4];           /* 已收到的数字字符 */
uint8_t       piDigitCount = 0;      /* 已收到几位 */
unsigned long piStateMs    = 0;      /* 进入当前状态的时刻，用于超时 */
char          piLineBuf[8];          /* 原始行缓存，仅用于调试回显 */
uint8_t       piLineLen    = 0;

/* ---- 每首音频的实际时长（毫秒）----
 * 决定"什么时候算这首播完了，可以放下一首"。
 * 下面的数值是用脚本解析 mp3 帧头【实测】出来的（全部 64kbps / 32000Hz）：
 *   001=5.50s 002=10.30s 003=6.65s 004=2.76s 005=12.22s 006=6.41s
 *   007=5.54s 008=4.01s 009=5.93s 010=6.60s 011=5.50s
 * 已各加约 300ms 余量，避免还没播完就切歌。
 * ⚠️ 换了音频就改这张表；超出表范围的曲目用 MP3_TRACK_DEFAULT_MS。 */
const uint16_t TRACK_MS_TABLE[MP3_FILE_COUNT + 1] = {
  0,       /* [0] 占位，曲目号从 1 开始 */
  5800,    /* 001   5.50s */
  10600,   /* 002  10.30s */
  6950,    /* 003   6.65s */
  3060,    /* 004   2.76s */
  12520,   /* 005  12.22s */
  6710,    /* 006   6.41s */
  5840,    /* 007   5.54s */
  4310,    /* 008   4.01s */
  6230,    /* 009   5.93s */
  6900,    /* 010   6.60s */
  5800     /* 011   5.50s */
};
#define MP3_TRACK_DEFAULT_MS  6000UL   /* 表里没有的曲目，按 6 秒估算 */

/* ===========================================================================
 * 七、函数声明
 * ===========================================================================*/

/* 按键 */
void     keyInit(Key &k);
void     keyReport(const Key &k);
void     keyLog(const Key &k, const char *msg);
KeyEvent keyUpdate(Key &k);
void     updateButtons();

/* 时间 */
void     adjustMinutes(int delta);
void     updateClock();
void     onMinuteChanged(int minuteOfDay);

/* 灯 */
void     ledOn(uint8_t pin);
void     ledOff(uint8_t pin);
void     ledSelfTest();
void     ledTrigger(uint8_t pin, bool &activeFlag, unsigned long &startTime);
void     ledAutoOff(uint8_t pin, bool &activeFlag, unsigned long startTime);
void     updateLeds();

/* OLED */
void     drawDisplay();

/* MP3 */
void     mp3Init();
void     mp3Service();
void     mp3PlayTrack(uint8_t track);
void     queuePush(uint8_t track);
bool     queuePop(uint8_t *track);
unsigned long trackMsOf(uint8_t track);

/* 树莓派串口协议 */
void     piResetState();
void     piFeedByte(char c);
void     piHandleCommand(int track);
void     piAck();
void     piErr();
void     piService();

/* 工具 */
void     printHexByte(uint8_t b);

/* ===========================================================================
 * 八、setup
 * ===========================================================================*/

void setup() {
  /* ---- 串口：D0/D1，与树莓派通信（调试打印也走这里）---- */
  Serial.begin(9600);

  DBG_PRINTLN();
  DBG_PRINTLN(F("=== Combined: 吃药提醒 + 树莓派串口 ==="));
  DBG_PRINTLN(F("08:00->D3 / 14:00->D4 / 20:00->D2   串口 9600 收 0001~0011"));
  DBG_PRINTLN(F("[TEST] 手动测试：按 A3 进设置模式，再同时按住 A1+A0 -> D3亮5秒 + 播001.mp3"));
  DBG_PRINTLN(F("[TEST] 另一办法：在设置模式下用 A1 把时间调到 08:00 也会触发提醒"));

  /* ---- 灯：先设为"熄灭电平"再设为输出，避免共阳接法上电瞬间闪一下 ---- */
  digitalWrite(PIN_LED_MORNING, LED_OFF_LEVEL);
  digitalWrite(PIN_LED_NOON,    LED_OFF_LEVEL);
  digitalWrite(PIN_LED_EVENING, LED_OFF_LEVEL);
  pinMode(PIN_LED_MORNING, OUTPUT);
  pinMode(PIN_LED_NOON,    OUTPUT);
  pinMode(PIN_LED_EVENING, OUTPUT);

  /* ---- 按键 ---- */
  keyInit(keyMinus);
  keyInit(keyPlus);
  keyInit(keyExit);
  keyInit(keySet);

  /* ---- OLED ---- */
  u8g2.begin();

  /* ---- RTC 时钟模块（硬件 I2C：A4=SDA / A5=SCL）---- */
  Wire.begin();
#if TIME_SOURCE == 1
  if (!rtc.begin()) {
    /* 初始化失败 -> 回退到软件时钟（curHour/curMinute 保持 07:59 初值） */
    rtcOk = false;
    DBG_PRINTLN(F("[RTC] 初始化失败！请检查 A4/A5 接线和模块供电"));
    DBG_PRINTLN(F("[RTC] 已回退到软件时钟模式，从 07:59 开始走时"));
  } else {
    rtcOk = true;

    /* 检测掉电：DS3231 电池没电时时间会不准，用编译时间做一次粗略校准。
     * 精度只到分钟，之后请用设置模式校准。 */
    if (rtc.lostPower()) {
      DBG_PRINTLN(F("[RTC] 检测到掉电，用编译时间做一次粗略校准"));
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
    }

    /* 从 RTC 读取当前时间，覆盖掉 07:59 的初值 */
    DateTime now = rtc.now();
    curHour   = now.hour();
    curMinute = now.minute();

    DBG_PRINTLN(F("RTC initialized"));
    DBG_PRINT(F("[RTC] 当前时间 "));
    if (curHour   < 10) DBG_PRINT('0');
    DBG_PRINT(curHour);
    DBG_PRINT(':');
    if (curMinute < 10) DBG_PRINT('0');
    DBG_PRINTLN(curMinute);
  }
#endif

  /* ---- MP3 ---- */
  mp3Init();

  /* ---- 初始化走时基准 ---- */
  lastMinuteTick = millis();

  /* ---- 开机自检：灯各闪一下 + 打印按键初始电平 ---- */
  ledSelfTest();
  delay(50);                 /* 等按键电平稳定后再读，避免上电抖动 */
  keyReport(keyMinus);
  keyReport(keyPlus);
  keyReport(keyExit);
  keyReport(keySet);

  /* ---- 打印实际生效的时间来源 ---- */
#if TIME_SOURCE == 1
  if (rtcOk) {
    DBG_PRINTLN(F("[TIME] 实际时间来源：RTC 真实时钟"));
  } else {
    DBG_PRINTLN(F("[TIME] 实际时间来源：软件时钟（RTC 不可用，已回退）"));
  }
#else
  DBG_PRINTLN(F("[TIME] 实际时间来源：软件时钟"));
#endif

  DBG_PRINT(F("[TIME] start at "));
  if (curHour   < 10) DBG_PRINT('0');
  DBG_PRINT(curHour);
  DBG_PRINT(':');
  if (curMinute < 10) DBG_PRINT('0');
  DBG_PRINTLN(curMinute);

  /* ---- 上电自检（默认关闭，需要时把 USE_BOOT_TEST 改成 1）----
   * 只"登记"曲目到队列，真正的播放由 loop() 里的 mp3Service() 执行，
   * 所以不阻塞 setup。 */
#if USE_BOOT_TEST && USE_MP3
  DBG_PRINTLN(F("[TEST] 上电自检：播放 001.mp3"));
  queuePush(MP3_TRACK_MORNING);
#endif
}

/* ===========================================================================
 * 九、loop —— 协作式循环；MP3 库调用可能短时阻塞
 * ===========================================================================*/

void loop() {
  updateButtons();   /* 1. 扫描按键（状态机 + 30ms 消抖 + 手动测试组合键） */
  updateClock();     /* 2. 更新时钟 */

  /* 3. 分钟边沿检测：手动调时也会被检测到，同一分钟只执行一次 */
  int minuteOfDay = curHour * 60 + curMinute;
  if (minuteOfDay != lastMinuteOfDay) {
    onMinuteChanged(minuteOfDay);
    lastMinuteOfDay = minuteOfDay;
  }

  updateLeds();      /* 4. 处理灯 5 秒自动熄灭（非阻塞） */
  piService();       /* 5. 优先收树莓派指令：解析 + 回 ACK/ERR + 入队 */
  mp3Service();      /* 6. 推进播放队列；底层库调用可能短时阻塞 */

  /* 7. 刷新 OLED（约 250ms 一次，避免软件 I2C 占用过多时间） */
  if (millis() - lastDraw >= 250UL) {
    lastDraw = millis();
    drawDisplay();
  }
}

/* ===========================================================================
 * 十、按键（状态机）
 * ===========================================================================*/

/* 初始化一个按键：启用内部上拉（按下读到低电平），状态机置为空闲 */
void keyInit(Key &k) {
  pinMode(k.pin, INPUT_PULLUP);

  k.raw         = (digitalRead(k.pin) == LOW);
  k.lastStable  = k.raw;
  k.state       = KS_IDLE;
  k.tChange     = millis();
  k.tPress      = 0;
  k.tRepeat     = 0;
}

/* 串口打印按键事件，方便调试 */
void keyLog(const Key &k, const char *msg) {
  DBG_PRINT(F("[KEY] "));
  DBG_PRINT(k.name);
  DBG_PRINT(' ');
  DBG_PRINTLN(msg);
}

/* 开机打印每个按键的初始电平：若显示"按下"但你并没有按，说明接线有问题 */
void keyReport(const Key &k) {
  DBG_PRINT(F("[KEY] "));
  DBG_PRINT(k.name);
  if (k.raw) {
    DBG_PRINTLN(F(" 初始电平 = 按下  <-- 未按却显示按下？检查按键接线/是否接错引脚"));
  } else {
    DBG_PRINTLN(F(" 初始电平 = 松开  OK"));
  }
}

/* ---------------------------------------------------------------------------
 * 按键状态机核心：每轮 loop 必须对每个按键调用一次
 *   KS_IDLE    -- 等待一次"连续稳定 DEBOUNCE_MS 的按下"
 *   KS_PRESSED -- 已确认按下：做长按连发计时；检测到松手就重新武装
 *
 * 关键点：
 *   1. 电平一变就重新计时，必须连续稳定 DEBOUNCE_MS 才算数（滤掉抖动）
 *   2. 默认【按下就触发】，快速连点绝不丢键
 *   3. 松手后立刻重新武装，不等松手消抖
 * -------------------------------------------------------------------------*/
KeyEvent keyUpdate(Key &k) {
  bool reading = (digitalRead(k.pin) == LOW);   /* true = 按下 */

  if (reading != k.raw) {
    k.raw     = reading;
    k.tChange = millis();
  }

  bool stableNow = (millis() - k.tChange >= DEBOUNCE_MS);

  switch (k.state) {

    case KS_IDLE:
      if (reading && stableNow) {
        k.state      = KS_PRESSED;
        k.lastStable = true;
        k.tPress     = millis();
        k.tRepeat    = millis();
        keyLog(k, "PRESSED");

#if !KEY_TRIGGER_ON_RELEASE
        keyLog(k, "CLICK");
        return KEY_EVENT_CLICK;
#endif
      }
      break;

    case KS_PRESSED:
      /* 长按连发（仅 A0/A1 在 ENABLE_LONG_PRESS_REPEAT = 1 时启用） */
      if (k.repeatEnabled && reading &&
          (millis() - k.tPress  >= LONG_PRESS_MS) &&
          (millis() - k.tRepeat >= LONG_PRESS_REPEAT_MS)) {
        k.tRepeat = millis();
        return KEY_EVENT_REPEAT;
      }

      /* 松手 */
      if (!reading) {
#if KEY_TRIGGER_ON_RELEASE
        if (stableNow) {
          k.state      = KS_IDLE;
          k.lastStable = false;
          keyLog(k, "RELEASED");
          keyLog(k, "CLICK");
          return KEY_EVENT_CLICK;
        }
#else
        k.state      = KS_IDLE;
        k.lastStable = false;
        keyLog(k, "RELEASED");
#endif
      }
      break;

    default:
      k.state = KS_IDLE;
      break;
  }

  return KEY_EVENT_NONE;
}

void updateButtons() {
  /* 注意：四个按键的状态机必须每轮都被调用（否则状态会卡住），
     所以先取事件，再按"是否处于设置模式"决定要不要执行动作。 */

  /* ---- A3：进入设置模式 ---- */
  if (keyUpdate(keySet) == KEY_EVENT_CLICK) {
    setMode = true;
    DBG_PRINTLN(F("[MODE] SET mode ON"));
  }

  /* ---- A2：退出设置模式 ---- */
  if (keyUpdate(keyExit) == KEY_EVENT_CLICK) {
    setMode = false;
    DBG_PRINTLN(F("[MODE] SET mode OFF"));
  }

  /* ---- A1：时间 +1 分钟（非设置模式下不响应） ---- */
  KeyEvent evPlus = keyUpdate(keyPlus);
  if (setMode && (evPlus == KEY_EVENT_CLICK || evPlus == KEY_EVENT_REPEAT)) {
    adjustMinutes(+1);
    DBG_PRINTLN(F("[KEY] A1 -> +1 min"));
  }

  /* ---- A0：时间 -1 分钟（非设置模式下不响应） ---- */
  KeyEvent evMinus = keyUpdate(keyMinus);
  if (setMode && (evMinus == KEY_EVENT_CLICK || evMinus == KEY_EVENT_REPEAT)) {
    adjustMinutes(-1);
    DBG_PRINTLN(F("[KEY] A0 -> -1 min"));
  }

  /* ---- 手动测试入口：设置模式下【同时按住 A1 + A0】----
   * 触发一次"模拟 08:00 提醒"：D3 亮 5 秒 + 播放 001.mp3。
   *
   * 为什么用 A1 + A0 而不是 A1 + A2：
   *   A2 是"退出设置模式"键，按下会立刻把 setMode 置为 false。
   *   若把它编进组合，就必须改动 A2 原有的处理去抑制退出动作，
   *   会破坏"退出设置"这个既有功能。改用两个调时键则完全不必动原逻辑。
   *
   * 独立新增的入口：只读 keyPlus / keyMinus 的 lastStable，
   * 不参与上面任何按键的事件判定；用上升沿触发，按住不放只触发一次。
   * 同时按住时 A1 的 +1 和 A0 的 -1 各触发一次，时间净变化为 0。 */
  static bool testComboPrev = false;
  bool testComboNow = setMode && keyPlus.lastStable && keyMinus.lastStable;
  if (testComboNow && !testComboPrev) {
    ledTrigger(PIN_LED_MORNING, morningLedActive, morningLedStart);
    DBG_PRINTLN(F("[TEST] A1+A0 手动测试 -> D3 亮5秒 + 播报曲目1"));
    queuePush(MP3_TRACK_MORNING);
  }
  testComboPrev = testComboNow;
}

/* ===========================================================================
 * 十一、时间处理
 * ===========================================================================*/

/* 按分钟数增减时间，自动处理跨小时 / 跨天（0~1439 循环） */
void adjustMinutes(int delta) {
  int total = curHour * 60 + curMinute + delta;
  total %= 1440;
  if (total < 0) total += 1440;      /* 借位处理负数 */

  curHour   = total / 60;
  curMinute = total % 60;

#if TIME_SOURCE == 1
  /* 使用 RTC 时把调整结果同步写回硬件时钟：读出当前日期，只替换时和分，
   * 日期保持不变（秒归零）。断电重启也不会丢。 */
  if (rtcOk) {
    DateTime now = rtc.now();
    rtc.adjust(DateTime(now.year(), now.month(), now.day(), curHour, curMinute, 0));
  }
#endif
}

/* 更新当前时间 */
void updateClock() {
#if TIME_SOURCE == 1
  if (rtcOk) {
    /* ---- 外部 RTC：每 200ms 读取一次真实时间 ---- */
    static unsigned long lastRead = 0;
    if (millis() - lastRead >= 200UL) {
      lastRead = millis();
      DateTime now = rtc.now();
      curHour   = now.hour();
      curMinute = now.minute();
    }
    return;                          /* RTC 可用 -> 不走软件时钟 */
  }
  /* rtcOk == false（模块没接好）-> 落到下面的软件时钟分支继续走时 */
#endif

  /* ---- 内部软件时钟：每 60000ms 走 1 分钟 ---- */
  if (setMode && PAUSE_TICK_IN_SET_MODE) {
    lastMinuteTick = millis();
  } else if (millis() - lastMinuteTick >= 60000UL) {
    lastMinuteTick += 60000UL;       /* 累加而非赋值，避免累计漂移 */
    adjustMinutes(+1);
  }
}

/* ---------------------------------------------------------------------------
 * 时间跳到某一分钟时的处理（边沿触发，同一分钟只执行一次）
 * 三个吃药时间点都在这里判断，互不影响
 *
 * ⚠️ 曲目不再直接播放，而是调用 queuePush() 入队，
 *    由 loop() 里的 mp3Service() 统一按队列播放。
 *    这样定时提醒和树莓派指令共用同一条播放路径，不会互相打断。
 * -------------------------------------------------------------------------*/
void onMinuteChanged(int minuteOfDay) {
  /* 串口打印当前时间，方便观察走时是否正常 */
  DBG_PRINT(F("[TIME] "));
  if (curHour   < 10) DBG_PRINT('0');
  DBG_PRINT(curHour);
  DBG_PRINT(':');
  if (curMinute < 10) DBG_PRINT('0');
  DBG_PRINTLN(curMinute);

  /* --- 08:00 早上药：D3 亮 5 秒 + 语音 --- */
  if (minuteOfDay == MORNING_HOUR * 60 + MORNING_MINUTE) {
    ledTrigger(PIN_LED_MORNING, morningLedActive, morningLedStart);
    DBG_PRINTLN(F("[ALARM] 08:00 早上药 -> D3 亮5秒 + 播报曲目1"));
    queuePush(MP3_TRACK_MORNING);
  }

  /* --- 14:00 中午药：D4 亮 5 秒 + 语音 --- */
  if (minuteOfDay == NOON_HOUR * 60 + NOON_MINUTE) {
    ledTrigger(PIN_LED_NOON, noonLedActive, noonLedStart);
    DBG_PRINTLN(F("[ALARM] 14:00 中午药 -> D4 亮5秒 + 播报曲目2"));
    queuePush(MP3_TRACK_NOON);
  }

  /* --- 20:00 晚上药：D2 亮 5 秒 + 语音 --- */
  if (minuteOfDay == EVENING_HOUR * 60 + EVENING_MINUTE) {
    ledTrigger(PIN_LED_EVENING, eveningLedActive, eveningLedStart);
    DBG_PRINTLN(F("[ALARM] 20:00 晚上药 -> D2 亮5秒 + 播报曲目3"));
    queuePush(MP3_TRACK_EVENING);
  }
}

/* ===========================================================================
 * 十二、灯的处理
 * ===========================================================================*/

/* 点亮：电平由 LED_ACTIVE_HIGH 决定，切换共阴/共阳只需改那一个宏 */
void ledOn(uint8_t pin) {
  digitalWrite(pin, LED_ON_LEVEL);
}

/* 熄灭 */
void ledOff(uint8_t pin) {
  digitalWrite(pin, LED_OFF_LEVEL);
}

/* 开机自检：三盏灯依次闪一下，用来确认接线和极性是否正确 */
void ledSelfTest() {
  const uint8_t pins[3] = { PIN_LED_MORNING, PIN_LED_NOON, PIN_LED_EVENING };
  for (uint8_t i = 0; i < 3; i++) {
    ledOn(pins[i]);
    delay(200);
    ledOff(pins[i]);
    delay(100);
  }
  DBG_PRINTLN(F("[LED] self test done. 若刚才有灯不亮 -> 检查电阻/极性/LED_ACTIVE_HIGH"));
}

/* 点亮一盏灯并记录起始时刻 */
void ledTrigger(uint8_t pin, bool &activeFlag, unsigned long &startTime) {
  ledOn(pin);
  activeFlag = true;
  startTime  = millis();
}

/* 点亮满 LED_ON_MS（5 秒）后自动熄灭，非阻塞 */
void ledAutoOff(uint8_t pin, bool &activeFlag, unsigned long startTime) {
  if (activeFlag && (millis() - startTime >= LED_ON_MS)) {
    ledOff(pin);
    activeFlag = false;
    DBG_PRINT(F("[LED] D"));
    DBG_PRINT(pin);
    DBG_PRINTLN(F(" OFF (5s elapsed)"));
  }
}

void updateLeds() {
  /* 三盏灯使用同一套逻辑：点亮计时 -> 到 5 秒自动熄灭 */
  ledAutoOff(PIN_LED_MORNING, morningLedActive, morningLedStart);
  ledAutoOff(PIN_LED_NOON,    noonLedActive,    noonLedStart);
  ledAutoOff(PIN_LED_EVENING, eveningLedActive, eveningLedStart);
}

/* ===========================================================================
 * 十三、OLED 显示
 * ===========================================================================*/

void drawDisplay() {
  char buf[8];
  snprintf(buf, sizeof(buf), "%02d:%02d", curHour, curMinute);

  /* _1_ 模式只有 128 字节页缓冲：clearBuffer()/sendBuffer() 每次只写当前一页
     （第 0 页 = 顶部 8 行），下面的内容全在 8 行之外，所以屏幕会是黑的。
     必须用 firstPage()/nextPage() 把整屏分 8 页画完。 */
  u8g2.firstPage();
  do {
    /* ---- 大号时间 HH:MM，水平居中 ---- */
    u8g2.setFont(u8g2_font_logisoso32_tn);   /* _tn 字体只含数字与冒号，适合做时钟 */
    int w = u8g2.getStrWidth(buf);
    int x = (128 - w) / 2;
    if (x < 0) x = 0;
    u8g2.drawStr(x, 40, buf);

    /* ---- 分隔线 ---- */
    u8g2.drawHLine(0, 45, 128);

    /* ---- 底部状态栏 ---- */
    u8g2.setFont(u8g2_font_6x12_tf);

    if (setMode) {
      /* 设置模式：反白方块 + SET 提示 */
      u8g2.drawBox(0, 47, 34, 14);
      u8g2.setDrawColor(0);
      u8g2.drawStr(4, 58, "SET");
      u8g2.setDrawColor(1);
      u8g2.drawStr(40, 58, "A0- A1+ A2:X");   /* A0 减 / A1 加 / A2 退出 */
    } else {
      u8g2.drawStr(0, 58, "A3:SET");          /* A3 进入设置 */
      /* 任意一盏灯亮着就提示 ALARM */
      if (morningLedActive || noonLedActive || eveningLedActive) {
        u8g2.drawStr(88, 58, "ALARM");
      }
    }
  } while (u8g2.nextPage());
}

/* ===========================================================================
 * 十四、MP3 语音播报（统一播放路径）
 *
 *   三个触发来源 -> queuePush() -> 队列 -> mp3Service() -> mp3PlayTrack()
 *     1. 定时吃药提醒   onMinuteChanged()
 *     2. 手动测试组合键 updateButtons()
 *     3. 树莓派指令     piHandleCommand()
 * ===========================================================================*/

/* 初始化 MP3 模块（USE_MP3 = 0 时整个函数体不编译）
 *
 * GD5800 模块上电后需要一点时间初始化，这里用 delay 等待。
 * 这是 setup() 里的延时，不影响运行时的响应。
 * setVolume() 内部同样会阻塞约 0.17~1.2 秒，也只在 setup 里调用一次。 */
void mp3Init() {
#if USE_MP3
  mp356.begin(MP3_BAUD);             /* 先把软串口 TX 拉到空闲高电平 */
  delay(MP3_POWER_ON_MS);            /* 再等模块上电初始化完成 */
  mp356.setVolume(MP3_VOLUME);       /* 音量 0~30 */

  DBG_PRINTLN(F("[MP3] GD5800 ready: D9=RX<-T, D11=TX->R"));
  DBG_PRINT(F("[MP3] 音量 "));
  DBG_PRINTLN(MP3_VOLUME);
#else
  DBG_PRINTLN(F("[MP3] disabled (USE_MP3 = 0)"));
#endif
}

/* ---------------------------------------------------------------------------
 * 入队。三个触发来源都调用这个函数登记待播曲目。
 *
 * 队列满时丢弃【最旧】的一条并保留新指令：
 * 文档没有规定队列满的行为，这里选"保留最新意图"——后到的指令更可能反映
 * 当前真实状态。无论是否溢出，树莓派指令都必须回 ACK（文档要求）。
 * -------------------------------------------------------------------------*/
void queuePush(uint8_t track) {
#if USE_MP3
  if (queueCount >= QUEUE_SIZE) {
    queueHead = (queueHead + 1) % QUEUE_SIZE;   /* 丢掉最旧的一条 */
    queueCount--;
    DBG_PRINTLN(F("[队列] 已满，丢弃最旧一条"));
  }
  queueBuf[queueTail] = track;
  queueTail = (queueTail + 1) % QUEUE_SIZE;
  queueCount++;

  DBG_PRINT(F("[队列] 入队 "));
  DBG_PRINT(track);
  DBG_PRINT(F("，当前 "));
  DBG_PRINT(queueCount);
  DBG_PRINTLN(F(" 条"));
#else
  (void)track;
#endif
}

/* 出队，成功返回 true */
bool queuePop(uint8_t *track) {
#if USE_MP3
  if (queueCount == 0) return false;
  *track = queueBuf[queueHead];
  queueHead = (queueHead + 1) % QUEUE_SIZE;
  queueCount--;
  return true;
#else
  (void)track;
  return false;
#endif
}

/* 查表得到某首曲目的预估播放时长 */
unsigned long trackMsOf(uint8_t track) {
  if (track >= 1 && track <= MP3_FILE_COUNT) return TRACK_MS_TABLE[track];
  return MP3_TRACK_DEFAULT_MS;
}

/* ---------------------------------------------------------------------------
 * 低层播放：立即播放指定曲目（只应由 mp3Service() 调用）
 *
 * ⚠️ 这个函数会阻塞约 170ms~1.2 秒
 *    （GD5800_Serial::sendCommand 内部有 waitUntilAvailable(1000) + 150ms 排空）
 * -------------------------------------------------------------------------*/
void mp3PlayTrack(uint8_t track) {
#if USE_MP3
  if (track < 1 || track > MP3_FILE_COUNT) {
    /* 指令合法但模块里没有这个文件，跳过不播，避免播到不存在的曲目 */
    DBG_PRINT(F("[mp3] 模块内无曲目 "));
    DBG_PRINT(track);
    DBG_PRINT(F("（当前只有 1~"));
    DBG_PRINT(MP3_FILE_COUNT);
    DBG_PRINTLN(F("），跳过"));
    return;
  }

  DBG_PRINT(F("[mp3] playFileByIndexNumber("));
  DBG_PRINT(track);
  DBG_PRINTLN(F(")"));
  mp356.playFileByIndexNumber(track);   /* 阻塞约 0.17~1.2 秒 */
#else
  (void)track;
#endif
}

/* ---------------------------------------------------------------------------
 * 队列推进：没有在播 且 队列非空 -> 取出下一条播放
 *
 * "播完"是靠 TRACK_MS_TABLE 里的实测时长估算的，不是真的查询模块状态。
 * 原因：库里的 getStatus() 对板载存储不可靠（文档明确说 STOPPED 几乎不返回），
 *       而且它内部最多查询 4 次、每次一轮 sendCommand，最坏阻塞近 5 秒，
 *       放进 loop() 会直接破坏与树莓派的实时通信。
 * -------------------------------------------------------------------------*/
void mp3Service() {
#if USE_MP3
  if (isPlaying) {
    if (millis() - playStartMs < curTrackMs) {
      return;                       /* 还没放完，等 */
    }
    isPlaying = false;              /* 按实测时长认为放完了 */
    DBG_PRINTLN(F("[mp3] 本曲结束，检查队列"));
  }

  uint8_t track;
  if (!queuePop(&track)) return;

  mp3PlayTrack(track);

  /* 计时从播放调用【返回后】开始算，避免把阻塞时间算进曲目时长 */
  curTrack    = track;
  curTrackMs  = trackMsOf(track);
  playStartMs = millis();
  isPlaying   = true;
#endif
}

/* ===========================================================================
 * 十五、树莓派串口协议（逐字节状态机，不使用 readString/readBytes）
 *
 * 文档《R3串口通信对接说明.md》：
 *   下行 "0005\n"  -> 有效指令回 "ACK\n"，未知指令回 "ERR\n"
 *   无校验和、无包头、无长度、无重传、无心跳
 *   指令入队后立即回复 ACK，不等待音频播放结束；树莓派最多等待 2.0 秒
 * ===========================================================================*/

/* 复位解析状态机 */
void piResetState() {
  piState      = PI_WAIT_DIGIT;
  piDigitCount = 0;
  piLineLen    = 0;
}

/* 每收到一个字节就喂进来。
 *
 * 协议：4 位数字 + '\n'，兼容忽略 '\r'。
 *   - '\r'     : 直接忽略
 *   - '\n'     : 结算。正好 4 位数字 -> 有效；否则 -> 格式错误
 *   - '0'~'9'  : 累积，超过 4 位标记为格式错误
 *   - 其它字符 : 立即判定本行格式错误，丢弃重来
 */
void piFeedByte(char c) {
  /* 记录原始行用于调试回显 */
  if (piLineLen < sizeof(piLineBuf)) piLineBuf[piLineLen++] = c;

  /* --- 回车：忽略 --- */
  if (c == '\r') {
    return;
  }

  /* --- 换行：一行的结束，开始结算 --- */
  if (c == '\n') {
    if (piDigitCount == 4) {
      int num = (piDigits[0] - '0') * 1000
              + (piDigits[1] - '0') * 100
              + (piDigits[2] - '0') * 10
              + (piDigits[3] - '0');
      piHandleCommand(num);
    } else {
      DBG_PRINT(F("RX(malformed, digits="));
      DBG_PRINT(piDigitCount);
      DBG_PRINTLN(F(") 已忽略"));
#if MALFORMED_REPLY_ERR
      piErr();
#endif
    }
    piResetState();
    return;
  }

  /* --- 数字：累积 --- */
  if (c >= '0' && c <= '9') {
    if (piState == PI_WAIT_DIGIT) {
      piState   = PI_IN_DIGITS;
      piStateMs = millis();        /* 开始计时，用于超时保护 */
    }
    if (piDigitCount < 4) {
      piDigits[piDigitCount++] = c;
    } else {
      piDigitCount = 5;            /* 用一个不可能等于 4 的值标记非法 */
    }
    return;
  }

  /* --- 其它任意字符：整行作废 --- */
  DBG_PRINT(F("RX(unexpected char 0x"));
  printHexByte((uint8_t)c);
  DBG_PRINTLN(F(") 整行丢弃"));
  piResetState();
}

/* 处理一条格式正确的 4 位指令（值已转成整数） */
void piHandleCommand(int track) {
  /* 打印收到的原始行 + 十六进制，便于和树莓派对账 */
  DBG_PRINT(F("RX: \""));
  for (uint8_t i = 0; i < piLineLen; i++) {
    char c = piLineBuf[i];
    if (c == '\n' || c == '\r') continue;   /* 行尾符不放进引号里 */
    DBG_PRINT(c);
  }
  DBG_PRINT(F("\"  ["));
  for (uint8_t i = 0; i < piLineLen; i++) {
    printHexByte((uint8_t)piLineBuf[i]);
    if (i + 1 < piLineLen) DBG_PRINT(' ');
  }
  DBG_PRINTLN(']');

  /* --- 判断指令是否在有效范围内（文档规定 0001~0011） --- */
  if (track < CMD_MIN || track > CMD_MAX) {
    DBG_PRINT(F("未知指令 "));
    DBG_PRINTLN(track);
    piErr();
    return;
  }

  /* --- 有效指令：先入队，再立刻回 ACK ---
   * loop() 会优先执行 piService()，尽量在启动下一条音频前完成回复。 */
  queuePush((uint8_t)track);
  piAck();
}

/* 回复 ACK\n（这一行必须永远发出，不受 DEBUG_SERIAL 影响） */
void piAck() {
  Serial.print(F("ACK\n"));
  DBG_PRINTLN(F("TX: \"ACK\\n\"  [41 43 4B 0A]"));
}

/* 回复 ERR\n（这一行必须永远发出，不受 DEBUG_SERIAL 影响） */
void piErr() {
  Serial.print(F("ERR\n"));
  DBG_PRINTLN(F("TX: \"ERR\\n\"  [45 52 52 0A]"));
}

/* 读取树莓派发来的字节，喂给状态机；并做"半截指令"超时保护 */
void piService() {
  while (Serial.available() > 0) {
    piFeedByte((char)Serial.read());
  }

  /* 如果数字收到一半就没了，超过 CMD_TIMEOUT_MS 就丢弃 */
  if (piState == PI_IN_DIGITS && (millis() - piStateMs) > CMD_TIMEOUT_MS) {
    DBG_PRINTLN(F("RX 超时：指令未收全，已丢弃"));
    piResetState();
  }
}

/* ===========================================================================
 * 十六、小工具
 * ===========================================================================*/

/* 打印一个字节的十六进制，固定两位（0x0A 打成 "0A" 而不是 "A"） */
void printHexByte(uint8_t b) {
#if DEBUG_SERIAL
  if (b < 0x10) Serial.print('0');
  Serial.print(b, HEX);
#endif
}
