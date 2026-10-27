import '@testing-library/jest-dom/vitest'

// jsdom não implementa o ciclo nativo de <dialog>; layout e teclado são
// conferidos também no navegador. Aqui habilitamos a consulta do modal aberto.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute('open', '')
  this.querySelector<HTMLElement>('button')?.focus()
}
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }

// O jsdom não tem PointerEvent: sem ele clientX, button e buttons chegam vazios aos handlers.
if (typeof window.PointerEvent === 'undefined') {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1 }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent
}
