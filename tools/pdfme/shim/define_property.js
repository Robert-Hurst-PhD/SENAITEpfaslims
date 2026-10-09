// senaite.pfas (GPL-2.0): our own implementation of the class-field helper the
// fontkit build imports, used in place of @swc/helpers (Apache-2.0, which
// cannot be combined with GPL-2.0). Sets a property the way a class field
// initialiser does.
export function _(obj, key, value) {
  if (key in obj) {
    Object.defineProperty(obj, key, { value: value, enumerable: true, configurable: true, writable: true });
  } else {
    obj[key] = value;
  }
  return obj;
}
export default _;
