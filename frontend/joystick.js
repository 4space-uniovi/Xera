/* Joystick virtual (ratón y táctil) sin dependencias.
 *
 * Uso:
 *   const joy = new Joystick(padElement, knobElement, (x, y) => { ... });
 *   joy.x, joy.y     -> valores actuales, enteros de -100 a 100
 *
 * x = steering (derecha positivo), y = throttle (arriba positivo).
 * Al soltar vuelve a (0, 0) y se avisa inmediatamente con onChange.
 */
(function (global) {
  "use strict";

  /** Convierte un desplazamiento en píxeles (dx, dy; y hacia abajo) en (x, y) de -100 a 100.
   *  El desplazamiento se limita a un círculo de radio `radius`, así se permiten diagonales. */
  function toXY(dx, dy, radius) {
    const dist = Math.hypot(dx, dy);
    if (dist > radius) { dx *= radius / dist; dy *= radius / dist; }
    const clamp = (v) => Math.max(-100, Math.min(100, Math.round(v)));
    return { x: clamp((dx / radius) * 100), y: clamp((-dy / radius) * 100), kx: dx, ky: dy };
  }

  class Joystick {
    constructor(pad, knob, onChange) {
      this.pad = pad;
      this.knob = knob;
      this.onChange = onChange || function () {};
      this.x = 0;
      this.y = 0;
      this.enabled = true;
      this.pointerId = null;

      pad.addEventListener("pointerdown", (e) => this._down(e));
      pad.addEventListener("pointermove", (e) => this._move(e));
      pad.addEventListener("pointerup", (e) => this._up(e));
      pad.addEventListener("pointercancel", (e) => this._up(e));
      pad.addEventListener("lostpointercapture", (e) => this._up(e));
      pad.addEventListener("contextmenu", (e) => e.preventDefault());
    }

    setEnabled(on) {
      this.enabled = on;
      this.pad.classList.toggle("disabled", !on);
      if (!on) this.reset();
    }

    /** Vuelve a (0,0) y avisa. */
    reset() {
      this.pointerId = null;
      this.pad.classList.remove("dragging");
      this._set(0, 0, 0, 0);
    }

    _radius() {
      // el pomo se mueve hasta que su centro llega al borde menos medio pomo
      const r = this.pad.getBoundingClientRect();
      return (r.width - this.knob.offsetWidth) / 2;
    }

    _down(e) {
      if (!this.enabled || this.pointerId !== null) return;
      this.pointerId = e.pointerId;
      this.pad.setPointerCapture(e.pointerId);
      this.pad.classList.add("dragging");
      this._move(e);
    }

    _move(e) {
      if (e.pointerId !== this.pointerId) return;
      const r = this.pad.getBoundingClientRect();
      const v = toXY(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2), this._radius());
      this._set(v.x, v.y, v.kx, v.ky);
    }

    _up(e) {
      if (e.pointerId !== this.pointerId) return;
      this.reset();
    }

    _set(x, y, kx, ky) {
      this.knob.style.transform = `translate(${kx}px, ${ky}px)`;
      if (x === this.x && y === this.y) return;
      this.x = x;
      this.y = y;
      this.onChange(x, y);
    }
  }

  global.Joystick = Joystick;
  global.Joystick.toXY = toXY;
})(window);
