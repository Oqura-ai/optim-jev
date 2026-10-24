// The mod runtime has Uint8Array.prototype.toBase64 (ES2025); TypeScript's es2023 lib doesn't declare it.
interface Uint8Array {
  toBase64(): string;
}
