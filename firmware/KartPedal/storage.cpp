#include "logger.h"
#include <sys/stat.h>
#include <unistd.h>
#include <cerrno>
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"
#include "driver/sdspi_host.h"
#include "esp_random.h"
#include "esp_mac.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"

static FILE *events,*journal,*data[2];
static sdmmc_card_t *card;
static char folder[132],uuid[37],device[24],hashHex[65];
static const char *sensor[]={"shoe","shin"};
static char files[2][36];
static uint8_t bootId[16];
static uint32_t epoch[2],completed[2][16],allCount[2];
static bool commit();
static uint32_t crc[2],count[2],total[2],maxWriteUs=0;
static uint64_t mark,firstSample[2],lastSample[2];static uint32_t gaps[2];
static bool syncFile(FILE *f){return f&&!ferror(f)&&fflush(f)==0&&fsync(fileno(f))==0;}
static FILE *createFile(const char*name){
  char p[190];snprintf(p,sizeof(p),"%s/%s",folder,name);return fopen(p,"wb");
}
static bool syncedClose(FILE *f){if(!f)return false;bool ok=syncFile(f);return fclose(f)==0&&ok;}
static bool mountCard(){
  sdmmc_host_t host=SDSPI_HOST_DEFAULT();host.slot=SPI2_HOST;host.max_freq_khz=1000;
  spi_bus_config_t bus{};bus.mosi_io_num=9;bus.miso_io_num=8;bus.sclk_io_num=7;bus.quadwp_io_num=-1;bus.quadhd_io_num=-1;
  if(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO)!=ESP_OK)return false;
  sdspi_device_config_t slot=SDSPI_DEVICE_CONFIG_DEFAULT();slot.host_id=SPI2_HOST;slot.gpio_cs=GPIO_NUM_4;
  esp_vfs_fat_sdmmc_mount_config_t m{};m.format_if_mount_failed=false;m.max_files=8;m.allocation_unit_size=16384;
  return esp_vfs_fat_sdspi_mount("/card",&host,&slot,&m,&card)==ESP_OK;
}
static bool createStream(int s,uint64_t start){
  snprintf(files[s],sizeof(files[s]),"imu_%s_e%06lu.bin",sensor[s],(unsigned long)epoch[s]);
  data[s]=createFile(files[s]);if(!data[s])return false;
  Header h=streamHeader(s,epoch[s],bootId,start);
  return fwrite(&h,1,sizeof(h),data[s])==sizeof(h)&&syncFile(data[s]);
}
bool openStorage(){
  uint8_t id[16],mac[6],digest[32];esp_fill_random(id,16);id[6]=(id[6]&15)|64;id[8]=(id[8]&63)|128;
  if(esp_read_mac(mac,ESP_MAC_WIFI_STA)!=ESP_OK||esp_partition_get_sha256(esp_ota_get_running_partition(),digest)!=ESP_OK)return false;
  for(int i=0;i<32;i++)snprintf(hashHex+2*i,3,"%02x",digest[i]);
  snprintf(device,sizeof(device),"KP-%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
  snprintf(uuid,sizeof(uuid),"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",id[0],id[1],id[2],id[3],id[4],id[5],id[6],id[7],id[8],id[9],id[10],id[11],id[12],id[13],id[14],id[15]);
  memcpy(bootId,id,16);
  snprintf(folder,sizeof(folder),"/card/%s",device);
  if(mkdir(folder,0777)&&errno!=EEXIST)return false;
  snprintf(folder,sizeof(folder),"/card/%s/%s",device,uuid);if(mkdir(folder,0777))return false;
  FILE *m=createFile("meta.json");if(!m)return false;
  uint64_t start=nowUs();
  fprintf(m,"{\"schema\":2,\"device_id\":\"%s\",\"side\":\"%s\",\"boot_uuid\":\"%s\",\"firmware_sha256\":\"%s\",\"start_us\":%llu,\"power_mode\":\"%s\",\"calibration_id\":null,\"config\":{",device,KP_LEFT?"L":"R",uuid,hashHex,start,bench?"USB_BENCH":"WEARABLE_EXPECTED_USB_ABSENT");
  for(int i=0;i<2;i++)fprintf(m,"%s\"%s\":{\"address\":%u,\"accel_odr_hz\":100,\"gyro_odr_hz\":100,\"accel_range_g\":16,\"gyro_range_dps\":2000,\"filter\":\"normal\",\"fifo\":\"header_acc_gyr_time\",\"raw_axes\":[\"x\",\"y\",\"z\"]}",i?",":"",sensor[i],104+i);
  fputs("}}\n",m);if(!syncedClose(m))return false;
  events=createFile("events.jsonl");journal=createFile("blocks.jsonl");if(!events||!journal)return false;
  for(int i=0;i<2;i++)if(!createStream(i,start))return false;
  return true;
}
bool mountRecordingCard(){return mountCard();}
bool probeCard(){
  if(!mountCard())return false;
  char path[64];snprintf(path,sizeof(path),"/card/KP_SMOKE_%08lx.TXT",(unsigned long)esp_random());
  const char pattern[]="KARTPEDAL-V18-SD-OK";struct stat st{};
  bool ok=stat(path,&st)!=0 && errno==ENOENT;
  FILE *f=ok?fopen(path,"wb"):nullptr;
  if(f){ok=fwrite(pattern,1,sizeof(pattern)-1,f)==sizeof(pattern)-1;ok=syncedClose(f)&&ok;}else ok=false;
  f=ok?fopen(path,"rb"):nullptr;char check[sizeof(pattern)]{};
  if(f){ok=fread(check,1,sizeof(check),f)==sizeof(pattern)-1&&!memcmp(check,pattern,sizeof(pattern));if(fclose(f))ok=false;}else ok=false;
  if(esp_vfs_fat_sdcard_unmount("/card",card)!=ESP_OK)ok=false;
  if(spi_bus_free(SPI2_HOST)!=ESP_OK)ok=false;
  Serial.printf("%s • inspect %s on the PC\n",ok?"Exact readback":"Readback failed",path);
  return ok;
}
static bool append(const Item &i){
  unsigned s=i.stream;
  if(i.kind==EPOCH){
    if(epoch[s]>=15 || !commit() || fclose(data[s]))return false;
    completed[s][epoch[s]++]=total[s];total[s]=0;
    if(!createStream(s,i.r.us))return false;
    return fprintf(events,"{\"type\":\"epoch\",\"stream\":\"%s\",\"epoch\":%lu,\"t_us\":%llu}\n",sensor[s],(unsigned long)epoch[s],i.r.us)>0;
  }
  if(i.kind==SENSOR_FAULT || i.kind==FIFO_READ)
    return fprintf(events,"{\"type\":\"%s\",\"stream\":\"%s\",\"epoch\":%lu,\"t_us\":%llu,\"read_end_us\":%llu}\n",i.kind==SENSOR_FAULT?"sensor_fault":"fifo_read",sensor[s],(unsigned long)epoch[s],i.r.us,i.end)>0;
  if(i.kind==SAMPLE){
    if(fwrite(&i.r,1,30,data[s])!=30)return false;
    crc[s]=crcMore(crc[s],&i.r,30);count[s]++;allCount[s]++;if(!firstSample[s])firstSample[s]=i.r.us;lastSample[s]=i.r.us;return true;
  }
  if(i.kind==ANCHOR)return fprintf(events,"{\"type\":\"anchor\",\"stream\":\"%s\",\"epoch\":%lu,\"t_us\":%llu,\"tick24\":%lu,\"read_start_us\":%llu,\"read_end_us\":%llu,\"uncertainty_us\":%llu}\n",sensor[s],(unsigned long)epoch[s],(i.r.us+i.end)/2,(unsigned long)i.r.tick,i.r.us,i.end,(i.end-i.r.us+1)/2)>0;
  if(i.kind==EDGE)return fprintf(events,"{\"type\":\"marker\",\"marker_id\":\"%lu\",\"edge\":\"%s\",\"t_us\":%llu}\n",(unsigned long)i.r.seq,i.detail?"rise":"fall",i.r.us)>0;
  if(i.kind==GAP){
    gaps[s]++;char lost[16]="null";if(i.detail)snprintf(lost,sizeof(lost),"%lu",(unsigned long)i.detail);
    return fprintf(events,"{\"type\":\"gap\",\"stream\":\"%s\",\"epoch\":%lu,\"seq\":%lu,\"lost\":%s,\"t_us\":%llu}\n",sensor[s],(unsigned long)epoch[s],(unsigned long)i.r.seq,lost,i.r.us)>0;
  }
  return fprintf(events,"{\"type\":\"voltage\",\"mv\":%lu,\"t_us\":%llu}\n",(unsigned long)i.detail,i.r.us)>0;
}
static bool commit(){
  if(!syncFile(events))return false;long watermark=ftell(events);if(watermark<0)return false;mark=watermark;
  for(int i=0;i<2;i++)if(count[i]){
    if(!syncFile(data[i]))return false;
    if(fprintf(journal,"{\"type\":\"block\",\"file\":\"%s\",\"offset\":%lu,\"count\":%lu,\"length\":%lu,\"crc32\":%lu,\"events_end\":%llu}\n",files[i],48ul+30ul*total[i],(unsigned long)count[i],30ul*count[i],(unsigned long)crc[i],mark)<=0)return false;
    total[i]+=count[i];count[i]=0;crc[i]=0;
  }
  return syncFile(journal);
}
static bool finish(){
  const char *why=reason==USER?"user":reason==LOW_BATTERY?"low_battery":"fault";
  fprintf(events,"{\"type\":\"close_intent\",\"t_us\":%llu,\"reason\":\"%s\"}\n",nowUs(),why);
  if(!commit())return false;
  FILE *summary=createFile("summary.json");if(!summary)return false;
  fprintf(summary,"{\"stop_reason\":\"%s\",\"queue_high_water\":%lu,\"max_io_us\":%lu,\"counts\":[%lu,%lu],\"gap_events\":[%lu,%lu],\"first_us\":[%llu,%llu],\"last_us\":[%llu,%llu]}\n",why,(unsigned long)highWater.load(),(unsigned long)maxWriteUs,(unsigned long)allCount[0],(unsigned long)allCount[1],(unsigned long)gaps[0],(unsigned long)gaps[1],firstSample[0],firstSample[1],lastSample[0],lastSample[1]);
  if(!syncedClose(summary))return false;
  fprintf(journal,"{\"type\":\"close\",\"t_us\":%llu,\"reason\":\"%s\",\"events_end\":%llu,\"streams\":[",nowUs(),why,mark);
  bool comma=false;
  for(int i=0;i<2;i++)for(uint32_t e=0;e<=epoch[i];e++){
    uint32_t n=e==epoch[i]?total[i]:completed[i][e];
    fprintf(journal,"%s{\"file\":\"imu_%s_e%06lu.bin\",\"end_offset\":%lu,\"record_count\":%lu}",comma?",":"",sensor[i],(unsigned long)e,48ul+30ul*n,(unsigned long)n);comma=true;
  }
  fputs("]}\n",journal);if(!syncFile(journal))return false;
  bool ok=true;for(auto f:data)if(fclose(f))ok=false;
  if(fclose(events))ok=false;if(fclose(journal))ok=false;
  return esp_vfs_fat_sdcard_unmount("/card",card)==ESP_OK&&ok;
}
void writer(void*){
  uint64_t checkpoint=nowUs();bool ok=true;
  for(;;){
    Item i;bool got=xQueueReceive(items,&i,pdMS_TO_TICKS(10))==pdTRUE;uint64_t start=nowUs();
    if(got && !append(i)){ok=false;break;}
    if(start-checkpoint>=1000000){if(!commit()){ok=false;break;}checkpoint=start;}
    maxWriteUs=std::max(maxWriteUs,(uint32_t)(nowUs()-start));
    if(!got&&statusCode==STOPPING&&acquisitionStopped&&activeSubmits==0&&uxQueueMessagesWaiting(items)==0){ok=finish();break;}
  }
  if(!ok)requestStop(FAULT);
  statusCode=(ok&&reason!=FAULT)?SAFE_OFF:ERROR_STOPPED;
  vTaskDelete(nullptr);
}
