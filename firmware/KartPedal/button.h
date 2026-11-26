#pragma once
#include <stdint.h>
enum PressEvent {NO_PRESS,SHORT_RELEASE,LONG_PRESS};
struct Button {
  bool raw=false,down=false,classified=false;
  uint32_t changed=0,started=0;
  PressEvent update(uint32_t now,bool level){
    if(level!=raw){raw=level;changed=now;}
    if(raw!=down && now-changed>=30){
      down=raw;
      if(down){started=changed;classified=false;}
      else if(!classified){
        uint32_t width=changed-started;classified=true;
        if(width>=2000)return LONG_PRESS;
        if(width>=50)return SHORT_RELEASE;
      }
    }
    if(down&&raw&&!classified&&now-started>=2000){classified=true;return LONG_PRESS;}
    return NO_PRESS;
  }
};

