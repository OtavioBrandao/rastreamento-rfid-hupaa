import '@testing-library/jest-dom/vitest'

// jsdom não implementa o ciclo nativo de <dialog>; layout e teclado são
// conferidos também no navegador. Aqui habilitamos a consulta do modal aberto.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute('open', '')
  this.querySelector<HTMLElement>('button')?.focus()
}
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
