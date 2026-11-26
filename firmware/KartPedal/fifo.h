#pragma once
#include "v18_format.h"
// Bosch BMI270 header-mode stream at equal accel/gyro ODR. Require complete paired samples.
struct Batch {
  Sample frames[19]{};
  uint32_t tick=0,lost=0;
  uint8_t count=0;
  bool hasTime=false;
};
inline uint32_t tick24(const uint8_t*p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16);}
inline bool parseFifo(const uint8_t*data,unsigned size,Batch &batch){
  unsigned pos=0;
  while(pos<size){
    switch(data[pos++]&0xfc){
      case 0x8c:{
        if(pos+12>size || batch.count==19)return false;
        auto &r=batch.frames[batch.count++];r.flags=1;
        for(int k=0;k<6;k++){
          int j=pos+2*((k+3)%6);r.axis[k]=(int16_t)(data[j]|((uint16_t)data[j+1]<<8));
          if(r.axis[k]>=32760||r.axis[k]<=-32760)r.flags|=4;
        }
        pos+=12;break;
      }
      case 0x44:
        if(pos+3>size)return false;
        batch.tick=tick24(data+pos);batch.hasTime=true;return true;
      case 0x40:
        if(pos>=size||batch.count||data[pos]==255)return false;
        batch.lost+=data[pos++];break;
      case 0x48:
        if(pos+4>size)return false;
        pos+=4;break;
      case 0x80:return batch.count==0;
      default:return false;
    }
  }
  return batch.count==0;
}

