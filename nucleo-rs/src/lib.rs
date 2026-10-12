//! DTE Chile en Rust: fase 8 del port (`docs/PLAN-PORT.md`). Cada módulo transcribe un
//! paquete de `nucleo/` (Go) y se juzga por los mismos gates: el corpus dorado byte a byte
//! (`test_dorado.py --port nucleo-rs/target/release/nucleo-dorado`), el contrato dorado y los
//! vectores por paquete. Python sigue siendo la referencia; Go, el producto, hasta que esto
//! pase todo.
pub mod almacen;
pub mod c14n;
pub mod certificacion;
pub mod firma;
pub mod htmlent;
pub mod pdf;
pub mod pdf417;
pub mod portal;
pub mod rcv;
pub mod rvd;
pub mod sii;
pub mod siiengine;
pub mod ted;
pub mod totales;
pub mod xmlgen;
pub mod xsd;
