// Rule weight → severity colour class. 100 → red, 50–80 → orange, 0 → blue.
export const weightClass = (weight: number) =>
  weight >= 100 ? "w-red" : weight >= 50 ? "w-orange" : "w-blue";
