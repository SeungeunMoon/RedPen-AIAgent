// Python span은 Unicode 코드 포인트 기준이다. JS UTF-16 인덱스로 자르지 않는다.
export function sliceText(text, start, end) {
  return Array.from(text).slice(start, end).join('')
}
