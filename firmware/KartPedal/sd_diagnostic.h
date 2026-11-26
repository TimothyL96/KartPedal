#pragma once
#include <stdint.h>

// A diagnostic belongs to one cold boot. Readback and unmount happen in probe().
struct SdDiagnostic {
  bool sampled = false;
  bool passed = false;
  uint32_t lastReport = 0;

  bool report(uint32_t now, bool requested, bool (*probe)()) {
    if (!sampled && requested) {
      passed = probe();
      sampled = true;
    }
    if (!sampled || (!requested && now - lastReport < 5000)) return false;
    lastReport = now;
    return true;
  }
};
