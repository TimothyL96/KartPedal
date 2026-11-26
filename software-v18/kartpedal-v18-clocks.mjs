// Fit one device epoch to two source-PTS observations. Never extrapolate.
export function fitClock(first, last) {
  if (!first || !last || ![first.deviceUs,last.deviceUs].every(Number.isSafeInteger)
      || ![first.pts,last.pts].every(Number.isFinite) || last.deviceUs <= first.deviceUs || last.pts <= first.pts) return null;
  const secondsPerUs = (last.pts - first.pts) / (last.deviceUs - first.deviceUs);
  return deviceUs => !Number.isSafeInteger(deviceUs) || deviceUs < first.deviceUs || deviceUs > last.deviceUs ? null :
    first.pts + (deviceUs - first.deviceUs) * secondsPerUs;
}
