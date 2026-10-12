//! DTE Chile en Rust: fase 8 del port (`docs/PLAN-PORT.md`). Cada módulo transcribe un
//! paquete de `nucleo/` (Go) y se juzga por los mismos gates: el corpus dorado byte a byte
//! (`test_dorado.py --port nucleo-rs/target/release/nucleo-dorado`), el contrato dorado y los
//! vectores por paquete. Python sigue siendo la referencia; Go, el producto, hasta que esto
//! pase todo.
/// `sql![a, b, c]`: los parámetros de una consulta.
#[macro_export]
macro_rules! sql {
    ($($x:expr),* $(,)?) => { [$($crate::servidor::AParam::sql($x)),*] };
}

pub mod almacen;
pub mod c14n;
pub mod certificacion;
pub mod cliutil;
pub mod conectores;
pub mod emision;
pub mod firma;
pub mod htmlent;
pub mod mcp;
pub mod pdf;
pub mod pdf417;
pub mod portal;
pub mod rcv;
pub mod rvd;
pub mod servidor;
pub mod sii;
pub mod siiengine;
pub mod ted;
pub mod totales;
pub mod valores;
pub mod xmlgen;
pub mod xsd;
