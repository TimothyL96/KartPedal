#include "logger.h"
#include "fifo.h"
#include <algorithm>
struct Imu {
  bmi2_dev dev{};
  uint8_t address;
  uint32_t seq=0,lastTick=0;
  uint64_t lastHost=0,lastRead=0,lastData=0;
  uint32_t lastReference=0;
  bool gap=false;
};
static Imu sensors[2];
static int8_t readReg(uint8_t reg,uint8_t *data,uint32_t n,void *ctx) {
  uint8_t a=*(uint8_t*)ctx;
  Wire.beginTransmission(a); Wire.write(reg);
  if(Wire.endTransmission(false) || Wire.requestFrom(a,(size_t)n)!=n) return -1;
  for(unsigned i=0;i<n;i++)data[i]=Wire.read();
  return 0;
}
static int8_t writeReg(uint8_t reg,const uint8_t *data,uint32_t n,void *ctx){
  Wire.beginTransmission(*(uint8_t*)ctx); Wire.write(reg);
  if(Wire.write(data,n)!=n)return -1;
  return Wire.endTransmission()? -1:0;
}
static void pauseUs(uint32_t us,void*){if(us>1000)delay(us/1000);delayMicroseconds(us%1000);}
bool setupSensors(int number){
  Wire.setBufferSize(256);
  if(!Wire.begin(5,6,100000))return false;
  Wire.setTimeOut(25);
  for(int i=0;i<number;i++){
    Imu &s=sensors[i]; s.address=0x68+i;
    uint8_t id=0;
    if(readReg(0,&id,1,&s.address)||id!=0x24)return false;
    auto &d=s.dev;d.intf=BMI2_I2C_INTF;d.intf_ptr=&s.address;d.read=readReg;
    d.write=writeReg;d.delay_us=pauseUs;d.read_write_len=32;
    if(bmi270_init(&d)!=BMI2_OK || bmi2_set_adv_power_save(0,&d)!=BMI2_OK)return false;
    bmi2_sens_config cfg[2]{};cfg[0].type=BMI2_ACCEL;cfg[1].type=BMI2_GYRO;
    if(bmi2_get_sensor_config(cfg,2,&d))return false;
    auto &a=cfg[0].cfg.acc;a.odr=BMI2_ACC_ODR_100HZ;a.range=BMI2_ACC_RANGE_16G;a.bwp=BMI2_ACC_NORMAL_AVG4;a.filter_perf=BMI2_PERF_OPT_MODE;
    auto &g=cfg[1].cfg.gyr;g.odr=BMI2_GYR_ODR_100HZ;g.range=BMI2_GYR_RANGE_2000;g.bwp=BMI2_GYR_NORMAL_MODE;g.filter_perf=BMI2_PERF_OPT_MODE;
    uint8_t types[]={BMI2_ACCEL,BMI2_GYRO};
    if(bmi2_set_sensor_config(cfg,2,&d)||bmi2_sensor_enable(types,2,&d)||
       bmi2_set_fifo_config(BMI2_FIFO_HEADER_EN|BMI2_FIFO_TIME_EN|BMI2_FIFO_ACC_EN|BMI2_FIFO_GYR_EN,1,&d))return false;
  }
  return true;
}
void probeSensors(int number){
  if(!setupSensors(number))Serial.println("FAIL ID or Bosch initialization; check straps, power, SDA/SCL");
  else for(int n=0;n<20;n++){
    for(int i=0;i<number;i++){
      bmi2_sens_data axes{};
      if(bmi2_get_sensor_data(&axes,&sensors[i].dev)){Serial.println("FAIL sensor data");break;}
      Serial.printf("0x%02X ID 0x24 a[g] %.3f %.3f %.3f gyro[dps] %.2f %.2f %.2f\n",sensors[i].address,
        axes.acc.x/2048.,axes.acc.y/2048.,axes.acc.z/2048.,axes.gyr.x/16.384,axes.gyr.y/16.384,axes.gyr.z/16.384);
    }
    delay(100);
  }
  Wire.end();
}
bool flushSensors(){
  for(auto &s:sensors){
    if(bmi2_set_command_register(BMI2_FIFO_FLUSH_CMD,&s.dev))return false;
    s.lastData=nowUs();
  }
  return true;
}
bool pollSensor(int index){
  auto &s=sensors[index];uint16_t bytes=0;
  if(bmi2_get_fifo_length(&bytes,&s.dev))return false;
  if(!bytes)return nowUs()-s.lastData<250000;
  // Stop on backlog beyond one bounded I2C burst; never discard old data silently.
  if(bytes>205)return false;
  // Extra space covers samples arriving during the bus transaction plus the time trailer.
  uint8_t fifo[256];int size=bytes+43;uint64_t fifoStart=nowUs();
  if(readReg(BMI2_FIFO_DATA_ADDR,fifo,size,&s.address))return false;
  uint64_t fifoEnd=nowUs();
  // Independent live clock read after drain, with its own host-time bracket.
  uint8_t timeRaw[3];uint64_t before=nowUs();
  if(readReg(0x18,timeRaw,3,&s.address))return false;
  uint64_t after=nowUs(),center=(after+before)/2;
  uint32_t reference=tick24(timeRaw);
  bool discontinuity=false;
  if(s.lastRead){
    uint64_t elapsed=center-s.lastRead;
    uint32_t ticks=(reference-s.lastReference)&0xffffffu;
    discontinuity=elapsed>=655360000ULL || fabs(ticks*39.0625-elapsed)>6000.+.015*elapsed;
  }
  s.lastRead=center;s.lastReference=reference;
  if(discontinuity){
    Item epoch{};epoch.kind=EPOCH;epoch.stream=index;epoch.r.us=fifoStart;if(!submit(epoch))return false;
    s.seq=0;s.lastHost=0;s.gap=true;
    uint8_t config=0;if(readReg(BMI2_INTERNAL_STATUS_ADDR,&config,1,&s.address)||(config&15)!=1)return false;
  }
  Item read{};read.kind=FIFO_READ;read.stream=index;read.r.us=fifoStart;read.end=fifoEnd;if(!submit(read))return false;
  Item anchor{};anchor.kind=ANCHOR;anchor.stream=index;anchor.r.us=before;anchor.end=after;anchor.r.tick=reference;
  if(!submit(anchor))return false;
  Batch batch;
  if(!parseFifo(fifo,size,batch))return false;
  if(batch.lost){
    s.seq+=batch.lost;s.gap=true;
    Item gap{};gap.kind=GAP;gap.stream=index;gap.r.us=center;gap.r.seq=s.seq;gap.detail=batch.lost;
    if(!submit(gap))return false;
  }
  if(!batch.count)return center-s.lastData<250000;
  if(!batch.hasTime)return false;
  s.lastData=center;
  uint32_t newest=batch.tick&0xffff00u;
  for(int k=0;k<batch.count;k++){
    auto &r=batch.frames[k];r.seq=s.seq++;if(s.gap){r.flags|=8;s.gap=false;}
    r.tick=(newest-(batch.count-1-k)*256u)&0xffffffu;
    uint32_t age=(reference-r.tick)&0xffffffu;
    if(age>8192 || center<age*39.0625)return false;
    r.us=center-llround(age*39.0625);
    if(after-before>6000)r.flags|=2;
    if(s.lastHost){
      uint32_t d=(r.tick-s.lastTick)&0xffffffu;
      if(d==0 || d>=0x800000 || r.us<=s.lastHost)return false;
      if(d!=256u && !(r.flags&8)){r.flags|=8|2;Item gap{};gap.kind=GAP;gap.stream=index;gap.r.us=r.us;gap.r.seq=r.seq;if(!submit(gap))return false;}
    }
    s.lastTick=r.tick;s.lastHost=r.us;
    Item sample{};sample.kind=SAMPLE;sample.stream=index;sample.r=r;
    if(!submit(sample))return false;
  }
  return true;
}
