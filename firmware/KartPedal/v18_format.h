#pragma once
#include <stdint.h>
#pragma pack(push,1)
struct Sample {uint64_t us;uint32_t seq,tick;int16_t axis[6];uint16_t flags;};
struct Header {char magic[8];uint16_t version,size,stride,stream;uint32_t epoch;uint8_t id[16];uint64_t opened;uint32_t crc;};
#pragma pack(pop)
static_assert(sizeof(Sample)==30 && sizeof(Header)==48,"V18 storage layout");
inline uint32_t crcMore(uint32_t old,const void*ptr,unsigned n){
  uint32_t c=~old;const auto p=static_cast<const uint8_t*>(ptr);
  for(unsigned i=0;i<n;i++){c^=p[i];for(int bit=0;bit<8;bit++)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}
  return ~c;
}
inline Header streamHeader(uint16_t stream,uint32_t epoch,const uint8_t id[16],uint64_t opened){
  Header h{};for(int i=0;i<6;i++)h.magic[i]="KPIMU2"[i];h.version=2;h.size=48;h.stride=30;h.stream=stream;
  h.epoch=epoch;for(int i=0;i<16;i++)h.id[i]=id[i];h.opened=opened;h.crc=crcMore(0,&h,44);return h;
}
inline bool goldenCheck(){
  uint8_t id[16];for(int i=0;i<16;i++)id[i]=i*17;
  Header h=streamHeader(0,0,id,1000000);
  Sample a{1010000,0,256,{100,-200,300,-400,500,-600},1};
  Sample b{1020000,1,512,{101,-201,301,-401,501,-601},1};
  return h.crc==0x4286723bu && crcMore(crcMore(0,&a,sizeof(a)),&b,sizeof(b))==0xa5325244u;
}

