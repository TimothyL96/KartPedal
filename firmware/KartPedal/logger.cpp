#include "logger.h"
#include "button.h"
#include "sd_diagnostic.h"
#include "esp_system.h"
#include <algorithm>

QueueHandle_t items;
std::atomic<int> statusCode{GRACE},reason{USER};
std::atomic<bool> acquisitionStopped{false};
std::atomic<uint32_t> highWater{0},stopMs{0};
std::atomic<unsigned> activeSubmits{0};
bool bench=false;
static constexpr uint8_t LED_PIN=21, BUTTON_PIN=0;
static uint32_t bootMs,lowMs,markerMs,markerId,lastVolt;
static Button button;
static SdDiagnostic sdDiagnostic;
static int markerPhase=0;
static esp_timer_handle_t stopTimer;
static void deadline(void*){if(statusCode==STOPPING)esp_restart();}
static void led(bool on){digitalWrite(LED_PIN,on?LOW:HIGH);}
void requestStop(Reason r){
  int old=reason.load();
  while(old<r&&!reason.compare_exchange_weak(old,(int)r)){}
  int recording=RECORD;
  if(statusCode.compare_exchange_strong(recording,STOPPING)){
    stopMs=millis();
    esp_timer_start_once(stopTimer,9900000);
  }
}
bool submit(Item &i){
  activeSubmits++;
  if(statusCode!=RECORD){activeSubmits--;return true;}
  if(xQueueSend(items,&i,0)!=pdTRUE){activeSubmits--;requestStop(FAULT);return false;}
  uint32_t n=uxQueueMessagesWaiting(items),previous=highWater.load();
  while(n>previous&&!highWater.compare_exchange_weak(previous,n)){}
  activeSubmits--;return true;
}
static int voltage(){
  int v[5];for(auto &mv:v)mv=analogReadMilliVolts(1);std::sort(v,v+5);
  return lroundf(v[2]*KP_BAT_GAIN+KP_BAT_OFFSET); // Two-point fit from disconnected-meter bench observations.
}
static void acquire(void*){
  while(statusCode==RECORD){
    for(int s=0;s<2 && statusCode==RECORD;s++)if(!pollSensor(s)){
      Item fault{};fault.kind=SENSOR_FAULT;fault.stream=s;fault.r.us=nowUs();submit(fault);requestStop(FAULT);
    }
    delay(10);
  }
  acquisitionStopped=true;vTaskDelete(nullptr);
}
static void start(bool usb){
  statusCode=STARTING;bench=usb;
  if(!bench && voltage()<3650){statusCode=ERROR_STOPPED;return;}
  items=xQueueCreate(1536,sizeof(Item));
  if(!goldenCheck()||!items||!setupSensors()||!mountRecordingCard()||(!bench&&voltage()<3650)||!openStorage()||!flushSensors()){statusCode=ERROR_STOPPED;return;}
  statusCode=RECORD;
  if(xTaskCreatePinnedToCore(writer,"sd",8192,nullptr,2,nullptr,1)!=pdPASS){statusCode=ERROR_STOPPED;return;}
  if(xTaskCreatePinnedToCore(acquire,"imu",8192,nullptr,3,nullptr,0)!=pdPASS){acquisitionStopped=true;requestStop(FAULT);}
}
static void controls(uint32_t ms){
  PressEvent input=button.update(ms,digitalRead(BUTTON_PIN)==LOW);
  if(input==SHORT_RELEASE&&statusCode==RECORD&&!markerPhase){
    markerPhase=1;markerMs=ms;markerId++;led(false);
  }
  if(input==LONG_PRESS){
    if(statusCode==GRACE){statusCode=MAINTENANCE;Serial.println("MAINTENANCE");}
    else if(statusCode==RECORD)requestStop(USER);
  }
}
void setup(){
  pinMode(LED_PIN,OUTPUT);led(false);pinMode(BUTTON_PIN,INPUT_PULLUP);
  Serial.begin(115200);analogReadResolution(12);analogSetPinAttenuation(1,ADC_11db);
  bootMs=millis();
  esp_timer_create_args_t timer{};timer.callback=deadline;timer.name="stop_limit";
  if(esp_timer_create(&timer,&stopTimer)!=ESP_OK){statusCode=ERROR_STOPPED;return;}
  if(esp_reset_reason()!=ESP_RST_POWERON){statusCode=ERROR_STOPPED;Serial.println("Unexpected reset; isolate power before cold start");}
}
void loop(){
  uint32_t ms=millis();controls(ms);
  switch(statusCode.load()){
    case GRACE:
      led((ms/250)%2==0);
      if(ms-bootMs>=8000&&!button.raw&&!button.down)start(false);
      break;
    case MAINTENANCE:{
      uint32_t p=ms%2100;led(p<150||(p>=300&&p<450));
      bool sdRequested=false;
      static char cmd[24];static size_t used=0;
      while(Serial.available()){char c=Serial.read();if(c=='\r')continue;
        if(c=='\n'){
          cmd[used]=0;used=0;
          if(!strcmp(cmd,"BENCH_RECORD")){start(true);break;}
          else if(!strcmp(cmd,"STATUS"))Serial.printf("MAINTENANCE side %s divider %d mV golden %s\n",KP_LEFT?"L":"R",voltage(),goldenCheck()?"PASS":"FAIL");
          else if(!strcmp(cmd,"PROBE_SHOE"))probeSensors(1);
          else if(!strcmp(cmd,"PROBE_BOTH"))probeSensors(2);
          else if(!strcmp(cmd,"CHECK_SD"))sdRequested=true;
          else Serial.println("STATUS | PROBE_SHOE | PROBE_BOTH | CHECK_SD | BENCH_RECORD");
        }
        else if(used<sizeof(cmd)-1)cmd[used++]=c;
      }
      if(statusCode==MAINTENANCE && sdDiagnostic.report(ms,sdRequested,probeCard))
        Serial.println(sdDiagnostic.passed?"SD PASS (this boot)":"SD FAIL (this boot): check FAT32, 3V3 and SPI pins");
      break;}
    case RECORD:
      if(!markerPhase)led((ms%2000)<100);
      else if((markerPhase==1&&ms-markerMs>=100)||(markerPhase==2&&ms-markerMs>=700)){
        led(markerPhase==1);Item i{};i.kind=EDGE;i.r.us=nowUs();i.r.seq=markerId;i.detail=markerPhase==1;submit(i);markerPhase++;markerMs=ms;
      }else if(markerPhase==3&&ms-markerMs>=100)markerPhase=0;
      if(ms-lastVolt>=1000){
        lastVolt=ms;int mv=voltage();Item i{};i.kind=VOLTAGE;i.r.us=nowUs();i.detail=mv;submit(i);
        if(!bench&&mv<3550)Serial.println("Battery warning");
        if(!bench&&mv<3400){if(!lowMs)lowMs=ms;if(ms-lowMs>=3000)requestStop(LOW_BATTERY);}else lowMs=0;
      }break;
    case STOPPING:
      led(ms/100%2==0);
      if(stopMs.load()&&ms-stopMs.load()>=9950)esp_restart(); // Non-cold reset enters ERROR_STOPPED, with no writes.
      break;
    case SAFE_OFF:led(true);break;
    case ERROR_STOPPED:{uint32_t p=ms%2400;led(p<150||(p>=300&&p<450)||(p>=600&&p<750));break;}
  }
  delay(2);
}
