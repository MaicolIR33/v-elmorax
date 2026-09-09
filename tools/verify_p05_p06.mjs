import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const base="/Users/os/Documents/ChatGPT/velmorax/outputs/01a06dff-d0de-74e3-9cd7-d01803d9682b";
const files=[
  ["P05",`${base}/Maicol_Andres_Ospina_Juan_David_Bastidas_P05_Matriz_Trazabilidad_Velmorax.xlsx`,[["Matriz","A1:T17"],["Huecos","A1:G12"],["Cobertura","A1:D18"],["Catálogos","A1:D12"]]],
  ["P06",`${base}/Maicol_Andres_Ospina_Juan_David_Bastidas_P06_Informe_Metricas_Calidad_Velmorax.xlsx`,[["Metricas_Codigo","A1:H19"],["Hallazgos","A1:H11"],["Plan_Mejora","A1:I10"],["Metricas_Proceso","A1:E14"]]],
];
for(const [label,file,ranges] of files){
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  for(const [sheetId,range] of ranges){
    const result=await wb.inspect({kind:"region",sheetId,range,maxChars:1800,tableMaxRows:4,tableMaxCols:20,tableMaxCellChars:55});
    console.log(`${label}:${sheetId}`,result.ndjson);
  }
  const errors=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},maxChars:3000});
  console.log(`${label}:ERROR_SCAN`,errors.ndjson || "NO_MATCHES");
}
