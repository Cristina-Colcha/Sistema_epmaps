function actualizarGrafico() {
  const tipo = document.getElementById("tipo-grafico").value;
  console.log("Actualizar gráfico a tipo:", tipo);
  // Aquí iría la lógica para cambiar el gráfico
}
function descargarPDF() {
  const content = document.querySelector('.col-md-9');
  html2pdf().from(content).save('reporte_mantenimiento.pdf');
}
function exportarExcel() {
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet([["Ejemplo", "Dato"], ["Estación A", 100]]);
  XLSX.utils.book_append_sheet(wb, ws, "Reporte");
  XLSX.writeFile(wb, "reporte_mantenimiento.xlsx");
}