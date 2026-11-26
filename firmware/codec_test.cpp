#include "KartPedal/v18_format.h"
#include "KartPedal/fifo.h"
#include "KartPedal/button.h"
#include "KartPedal/sd_diagnostic.h"
static unsigned probes;
static bool cardResult;
static bool countProbe(){++probes;return cardResult;}
// This tiny test DLL has no C runtime dependency on Windows machines without the SDK.
extern "C" void *memset(void*,int,decltype(sizeof(0)));
#pragma function(memset)
extern "C" void *memset(void *destination,int value,decltype(sizeof(0)) length){
  auto bytes=static_cast<volatile uint8_t*>(destination);
  for(decltype(length) i=0;i<length;i++)bytes[i]=static_cast<uint8_t>(value);
  return destination;
}
extern "C" __declspec(dllexport) int checkCodec(uint8_t *output){
  if(!goldenCheck())return 1;
  for(unsigned result=0;result<2;++result){
    SdDiagnostic sd;
    probes=0;cardResult=result!=0;
    if(sd.report(50,false,countProbe)||probes!=0)return 9;
    if(!sd.report(100,true,countProbe)||!sd.report(110,true,countProbe)||
       sd.report(5109,false,countProbe)||!sd.report(5110,false,countProbe)||
       sd.passed!=cardResult||probes!=1)return 10;
  }
  Button key;
  if(key.update(100,true)!=NO_PRESS||key.update(135,true)!=NO_PRESS||
     key.update(2090,false)!=NO_PRESS||key.update(2125,false)!=SHORT_RELEASE)return 7;
  if(key.update(3000,true)!=NO_PRESS||key.update(3030,true)!=NO_PRESS||key.update(5000,true)!=LONG_PRESS||
     key.update(5010,false)!=NO_PRESS||key.update(5040,false)!=NO_PRESS)return 8;
  const uint8_t fifo[]={0x40,2,0x48,0,0,0,0,0x8c,1,0,2,0,3,0,4,0,5,0,0xff,0x7f,0x44,0x12,0x34,0x56};
  Batch batch;
  if(!parseFifo(fifo,sizeof(fifo),batch)||batch.lost!=2||batch.count!=1||batch.tick!=0x563412||
     batch.frames[0].axis[0]!=4||batch.frames[0].axis[3]!=1||batch.frames[0].flags!=5)return 4;
  for(unsigned n=8;n<sizeof(fifo);n++){Batch shortRead;if(parseFifo(fifo,n,shortRead))return 5;}
  uint8_t bad[]={0x40,255};Batch invalid;if(parseFifo(bad,sizeof(bad),invalid))return 6;
  uint8_t id[16];for(int i=0;i<16;i++)id[i]=i*17;
  Header h=streamHeader(0,0,id,1000000);
  Sample frames[]={{1010000,0,256,{100,-200,300,-400,500,-600},1},
                   {1020000,1,512,{101,-201,301,-401,501,-601},1}};
  for(unsigned i=0;i<sizeof(h);i++)output[i]=reinterpret_cast<const uint8_t*>(&h)[i];
  for(unsigned i=0;i<sizeof(frames);i++)output[sizeof(h)+i]=reinterpret_cast<const uint8_t*>(frames)[i];
  return 0;
}
