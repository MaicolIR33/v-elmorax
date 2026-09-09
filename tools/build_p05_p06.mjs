import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = "/Users/os/Documents/ChatGPT/velmorax";
const OUT = path.join(ROOT, "outputs", "01a06dff-d0de-74e3-9cd7-d01803d9682b");
const TEAM = "Maicol Andrés Ospina · Juan David Bastidas";
const FICHA = "3229209";
const NAVY = "#17365D", BLUE = "#1F4E78", TEAL = "#0F6B78", SKY = "#DDEBF7";
const PALE = "#EAF3F8", WHITE = "#FFFFFF", GRID = "#B8C7D1", TEXT = "#243447";
const GREEN = "#E2F0D9", YELLOW = "#FFF2CC", RED = "#F4CCCC", GRAY = "#E7E6E6";

function mergeTitle(sheet, endCol, title, subtitle) {
  sheet.mergeCells(`A1:${endCol}1`);
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endCol}1`).format = { fill: NAVY, font: { bold: true, color: WHITE, size: 18 }, verticalAlignment: "center" };
  sheet.getRange("A1").format.horizontalAlignment = "left";
  sheet.getRange(`A1:${endCol}1`).format.rowHeight = 34;
  sheet.mergeCells(`A2:${endCol}2`);
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endCol}2`).format = { fill: PALE, font: { italic: true, color: TEXT, size: 10 }, wrapText: true, verticalAlignment: "center" };
  sheet.getRange(`A2:${endCol}2`).format.rowHeight = 31;
  sheet.mergeCells(`A3:${endCol}3`);
  sheet.getRange("A3").values = [[`Equipo: ${TEAM}   |   Ficha: ${FICHA}   |   Proyecto: Velmorax – flujo veterinario   |   Corte: 04/09/2026`]];
  sheet.getRange(`A3:${endCol}3`).format = { fill: "#D9EAD3", font: { bold: true, color: "#274E13", size: 10 }, verticalAlignment: "center" };
  sheet.getRange(`A3:${endCol}3`).format.rowHeight = 24;
  sheet.showGridLines = false;
}

function tableStyle(sheet, range, headerRange) {
  sheet.getRange(range).format = { font: { color: TEXT, size: 9 }, verticalAlignment: "top", wrapText: true, borders: { preset: "all", style: "thin", color: GRID } };
  sheet.getRange(headerRange).format = { fill: BLUE, font: { bold: true, color: WHITE, size: 9 }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: WHITE } };
  sheet.getRange(headerRange).format.rowHeight = 38;
}

function setWidths(sheet, widths) {
  for (const [col, width] of Object.entries(widths)) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
}

function statusFormatting(range) {
  range.conditionalFormats.add("containsText", { text: "Completa", format: { fill: GREEN, font: { color: "#274E13", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Aprobado", format: { fill: GREEN, font: { color: "#274E13", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Cumple", format: { fill: GREEN, font: { color: "#274E13", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Parcial", format: { fill: YELLOW, font: { color: "#7F6000", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "No cumple", format: { fill: RED, font: { color: "#9C0006", bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Pendiente", format: { fill: YELLOW, font: { color: "#7F6000" } } });
}

async function buildP05() {
  const wb = Workbook.create();
  const matriz = wb.worksheets.add("Matriz");
  const huecos = wb.worksheets.add("Huecos");
  const cobertura = wb.worksheets.add("Cobertura");
  const catalogos = wb.worksheets.add("Catálogos");

  mergeTitle(matriz, "T", "P05 · MATRIZ DE TRAZABILIDAD DEL PROYECTO", "GA2-AA3-EV08 · Relación verificable entre necesidad, diseño, implementación, prueba y evidencia.");
  const headers = [["N°","Problema","Objetivo","Stakeholder","Requisito","Título del requisito","Tipo","Regla de negocio","Historia (HU)","Proceso BPMN","D. secuencia","D. actividades","Componente","Endpoint","Caso de prueba","Resultado prueba","Evidencia","Ubicación evidencia","Estado implementación","Cobertura"]];
  matriz.getRange("A5:T5").values = headers;
  const rows = [
    [1,"Acceso no controlado al sistema","Permitir acceso seguro al personal autorizado","Veterinario / administrador","RF-01","Inicio de sesión veterinario","RF","RN-01 Credenciales válidas y sesión activa","HU-05","","DSQ-01","DAC-01","app/routers/web.py + app/services/auth.py","GET /login · POST /login","CP-01","Aprobado","Prueba automática: acceso al módulo clínico","tests/test_demo_smoke.py::test_demo_user_can_login_and_open_clinical_module","Implementado",null],
    [2,"Información clínica dispersa","Mostrar un panorama veterinario útil al ingresar","Veterinario","RF-02","Tablero veterinario por sede","RF","RN-02 Mostrar solo información del alcance de organización y sede","HU-05","","DSQ-01","DAC-01","app/services/dashboard.py + templates/dashboard.html","GET /dashboard","CP-02","Aprobado","Prueba automática del alcance y presentación veterinaria","tests/test_demo_smoke.py::test_veterinary_dashboard_is_visual_and_uses_veterinary_scope","Implementado",null],
    [3,"Citas gestionadas manualmente","Registrar y consultar citas de mascotas","Recepción / veterinario","RF-03","Gestión de citas","RF","RN-03 La cita debe asociar paciente, fecha, sede y profesional","HU-01","BPM-01","DSQ-02","DAC-02","app/services/appointments.py + app/routers/web.py","GET /appointments · POST /appointments","CP-03","Pendiente","Flujo implementado; falta prueba automática específica","app/services/appointments.py","Implementado",null],
    [4,"Datos del paciente incompletos","Crear expediente único de la mascota","Recepción / tutor","RF-04","Registro de paciente","RF","RN-04 El paciente pertenece a un tutor y a una organización","HU-02","BPM-02","DSQ-03","DAC-03","app/services/clinical.py + app/routers/web.py","GET /patients · POST /patients","CP-04","Pendiente","Servicio y formulario disponibles","app/services/clinical.py","Implementado",null],
    [5,"Historia clínica sin continuidad","Registrar consulta y evolución clínica","Veterinario","RF-05","Historia clínica veterinaria","RF","RN-05 Solo personal clínico autorizado registra atención","HU-03","BPM-03","DSQ-04","DAC-04","app/services/clinical.py + app/routers/web.py","GET /clinical · POST /clinical/records","CP-05","Pendiente","Servicio de historias clínicas implementado","app/services/clinical.py","Implementado",null],
    [6,"Inventario sin trazabilidad de acceso","Consultar y exportar inventario de forma protegida","Administrador / auxiliar","RF-06","Exportación protegida de inventario","RF","RN-06 La exportación exige una sesión autenticada","HU-04","","","","app/services/inventory.py + app/routers/web.py","GET /inventory/export","CP-06","Aprobado","Prueba automática impide exportación sin autenticación","tests/test_demo_smoke.py::test_inventory_export_requires_authenticated_access","Implementado",null],
    [7,"Olvido de contraseña bloquea la operación","Recuperar acceso sin intervención manual","Usuario registrado","RF-07","Restablecimiento de contraseña","RF","RN-07 El enlace de recuperación es temporal y de un solo uso","HU-06","","","","app/services/auth.py + app/routers/web.py","GET/POST /password-reset*","CP-07","Aprobado","Prueba automática genera enlace y permite nueva contraseña","tests/test_demo_smoke.py::test_password_reset_flow_generates_link_and_allows_new_login","Implementado",null],
    [8,"Formulario de acceso confuso","Presentar un ingreso limpio y comprensible","Usuario registrado","RF-08","Formulario de ingreso claro","Interfaz","RN-08 Solicitar únicamente correo y contraseña en el acceso","HU-05","","DSQ-01","DAC-01","templates/login.html","GET /login","CP-08","Aprobado","Prueba automática verifica formulario limpio","tests/test_demo_smoke.py::test_login_page_renders_clean_credentials_form","Implementado",null],
    [9,"Funciones expuestas a usuarios no autorizados","Restringir módulos por sesión y rol","Administrador / veterinario","RNF-01","Seguridad de sesión y roles","RNF","RN-09 Toda ruta protegida valida sesión y permisos","HU-05","","DSQ-01","DAC-01","app/services/auth.py + app/routers/web.py","Rutas web protegidas","CP-09","Aprobado","Pruebas de ingreso y exportación protegida","tests/test_demo_smoke.py","Implementado",null],
    [10,"Riesgo de mezclar datos entre sedes","Aislar la información por organización y ubicación","Administrador","RNF-02","Aislamiento por organización y sede","RNF","RN-10 Cada consulta debe filtrar el contexto activo","HU-05","","","DAC-01","app/services/scope.py + app/routers/web.py","Rutas autenticadas","CP-10","Pendiente","Mecanismo de alcance presente; falta batería específica","app/services/scope.py","Implementado",null],
    [11,"Paciente veterinario sin datos mínimos","Mantener información clínica básica consistente","Veterinario / tutor","DAT-01","Datos mínimos del paciente","Dato","RN-11 Nombre, especie, tutor y estado deben estar identificados","HU-02","BPM-02","DSQ-03","DAC-03","app/services/clinical.py + esquema de datos","POST /patients","CP-11","Pendiente","Campos gestionados en la capa clínica","app/services/clinical.py","Implementado",null],
    [12,"Medicamentos y lotes pueden vencer sin alerta","Controlar existencias, lote, vencimiento y cadena de frío","Administrador / auxiliar","RF-09","Control de inventario veterinario","RF","RN-12 Registrar lote, vencimiento y condición de almacenamiento cuando aplique","HU-04","","","","app/services/inventory.py + app/routers/web.py","GET/POST /inventory","CP-12","Pendiente","Módulo de inventario disponible; faltan cobertura funcional y modelado","app/services/inventory.py","Implementado",null],
  ];
  matriz.getRange(`A6:T${5 + rows.length}`).values = rows;
  for (let r = 6; r <= 17; r++) matriz.getRange(`T${r}`).formulas = [[`=IF(AND(I${r}<>"",OR(J${r}<>"",K${r}<>"",L${r}<>""),O${r}<>"",Q${r}<>"",P${r}="Aprobado",S${r}="Implementado"),"Completa",IF(COUNTA(B${r}:S${r})>0,"Parcial","Sin iniciar"))`]];
  tableStyle(matriz, "A5:T17", "A5:T5");
  matriz.getRange("A6:T17").format.rowHeight = 64;
  matriz.freezePanes.freezeRows(5); matriz.freezePanes.freezeColumns(5);
  matriz.getRange("G6:G17").dataValidation = { rule: { type: "list", formula1: "'Catálogos'!$A$6:$A$12" } };
  matriz.getRange("P6:P17").dataValidation = { rule: { type: "list", formula1: "'Catálogos'!$B$6:$B$10" } };
  matriz.getRange("S6:S17").dataValidation = { rule: { type: "list", formula1: "'Catálogos'!$C$6:$C$9" } };
  matriz.getRange("T6:T17").dataValidation = { rule: { type: "list", formula1: "'Catálogos'!$D$6:$D$8" } };
  statusFormatting(matriz.getRange("P6:T17"));
  setWidths(matriz,{A:5,B:24,C:25,D:20,E:10,F:24,G:12,H:31,I:10,J:11,K:11,L:11,M:30,N:27,O:10,P:14,Q:29,R:40,S:16,T:13});

  mergeTitle(huecos, "G", "P05 · REGISTRO DE HUECOS", "Vacíos detectados en trazabilidad y acciones concretas para cerrar cada brecha.");
  huecos.getRange("A5:G5").values = [["N°","Tipo de hueco","Elemento afectado","Descripción vacío","Causa","Acción correctiva","Estado"]];
  const gaps = [
    [1,"Prueba","RF-03 / CP-03","No existe prueba automática específica del alta y consulta de citas.","La suite actual prioriza humo, autenticación y tablero.","Agregar casos válidos, conflicto de horario y aislamiento por sede.","Abierto"],
    [2,"Prueba","RF-04 / CP-04","El registro de paciente no tiene evidencia automática dedicada.","Cobertura funcional aún incompleta.","Probar datos obligatorios, tutor y pertenencia a organización.","Abierto"],
    [3,"Prueba","RF-05 / CP-05","La creación de historia clínica no está cubierta por prueba automática.","Falta escenario clínico de extremo a extremo.","Crear prueba de consulta, diagnóstico y evolución autorizada.","Abierto"],
    [4,"Modelado","RF-06 / HU-04","La exportación de inventario no tiene BPMN ni diagramas UML asociados.","P04 se concentró en acceso, citas, pacientes e historia clínica.","Extender el modelado del flujo de inventario y exportación.","Abierto"],
    [5,"Modelado","RF-07 / HU-06","La recuperación de contraseña no tiene BPMN ni UML.","Flujo agregado después del conjunto principal de diagramas.","Añadir secuencia y actividades del token de recuperación.","Abierto"],
    [6,"Prueba","RNF-02 / CP-10","No hay una batería dedicada de aislamiento multi-sede.","El control se valida de forma parcial en el tablero.","Probar lectura y escritura cruzada entre dos organizaciones.","Abierto"],
    [7,"Modelado y prueba","RF-09 / HU-04","Lotes, vencimientos y cadena de frío carecen de modelado y prueba integral.","El módulo creció más rápido que su documentación.","Modelar recepción/alerta/salida y automatizar casos de vencimiento.","Abierto"],
  ];
  huecos.getRange("A6:G12").values = gaps;
  tableStyle(huecos,"A5:G12","A5:G5"); huecos.getRange("A6:G12").format.rowHeight = 70;
  huecos.freezePanes.freezeRows(5); huecos.getRange("G6:G12").dataValidation = { rule: { type: "list", values: ["Abierto","En curso","Cerrado"] } }; statusFormatting(huecos.getRange("G6:G12"));
  setWidths(huecos,{A:6,B:18,C:20,D:41,E:34,F:43,G:14});

  mergeTitle(cobertura, "D", "P05 · COBERTURA", "Indicadores calculados automáticamente a partir de las hojas Matriz y Huecos.");
  cobertura.getRange("A5:D5").values = [["Indicador","Valor","Meta sugerida","Lectura"]];
  const labels = [
    ["Total filas",null,"12","Requisitos y condiciones trazadas"],
    ["Requisitos con historia",null,"100%","Vínculo con HU"],
    ["Con modelado",null,"≥ 90%","BPMN, secuencia o actividades"],
    ["Con caso de prueba",null,"100%","Caso identificado"],
    ["Con evidencia aprobada",null,"≥ 80%","Resultado y evidencia verificable"],
    ["Cobertura completa",null,"≥ 90%","Cadena completa"],
    ["Cobertura parcial",null,"Tendencia a 0","Hay al menos un vínculo faltante"],
    ["Sin iniciar",null,"0","Sin trazabilidad"],
    ["% con historia",null,"100%","Historias / total"],
    ["% con prueba aprobada",null,"≥ 80%","Pruebas aprobadas / total"],
    ["Huecos abiertos",null,"0","Brechas no cerradas"],
  ];
  cobertura.getRange("A6:D16").values = labels;
  const formulas = [
    '=COUNTA(Matriz!E6:E17)', '=COUNTIF(Matriz!I6:I17,"<>"&"")', '=SUMPRODUCT(--(((Matriz!J6:J17<>"")+(Matriz!K6:K17<>"")+(Matriz!L6:L17<>""))>0))',
    '=COUNTIF(Matriz!O6:O17,"<>"&"")', '=COUNTIF(Matriz!P6:P17,"Aprobado")', '=COUNTIF(Matriz!T6:T17,"Completa")', '=COUNTIF(Matriz!T6:T17,"Parcial")', '=COUNTIF(Matriz!T6:T17,"Sin iniciar")',
    '=IF(B6=0,0,B7/B6)', '=IF(B6=0,0,B10/B6)', '=COUNTIF(Huecos!G6:G12,"Abierto")'
  ];
  for (let i=0;i<formulas.length;i++) cobertura.getRange(`B${6+i}`).formulas=[[formulas[i]]];
  cobertura.getRange("B14:B15").format.numberFormat = "0.0%";
  tableStyle(cobertura,"A5:D16","A5:D5"); cobertura.getRange("A6:D16").format.rowHeight=28; statusFormatting(cobertura.getRange("B6:B16"));
  setWidths(cobertura,{A:31,B:18,C:18,D:41}); cobertura.freezePanes.freezeRows(5);
  cobertura.mergeCells("A18:D18"); cobertura.getRange("A18").values=[["Interpretación: Velmorax tiene trazabilidad documental para todos los elementos priorizados, pero la cobertura completa baja donde aún faltan pruebas automáticas o diagramas específicos. Los huecos quedan registrados con acción correctiva."]];
  cobertura.getRange("A18:D18").format={fill:YELLOW,font:{color:"#7F6000",italic:true},wrapText:true,verticalAlignment:"center"}; cobertura.getRange("A18:D18").format.rowHeight=48;

  mergeTitle(catalogos, "D", "P05 · CATÁLOGOS", "Listas controladas utilizadas en la matriz para mantener consistencia en los registros.");
  catalogos.getRange("A5:D5").values = [["Tipo de requisito","Resultado de prueba","Estado implementación","Cobertura"]];
  catalogos.getRange("A6:A12").values=[["RF"],["RNF"],["Regla"],["Restricción"],["Dato"],["Interfaz"],["Rendimiento"]];
  catalogos.getRange("B6:B10").values=[["Pendiente"],["En ejecución"],["Aprobado"],["Fallido"],["Bloqueado"]];
  catalogos.getRange("C6:C9").values=[["Sin iniciar"],["En desarrollo"],["Implementado"],["Bloqueado"]];
  catalogos.getRange("D6:D8").values=[["Completa"],["Parcial"],["Sin iniciar"]];
  tableStyle(catalogos,"A5:D12","A5:D5"); setWidths(catalogos,{A:23,B:23,C:24,D:20});

  await fs.mkdir(OUT,{recursive:true});
  const file = await SpreadsheetFile.exportXlsx(wb);
  const outputPath=path.join(OUT,"Maicol_Andres_Ospina_Juan_David_Bastidas_P05_Matriz_Trazabilidad_Velmorax.xlsx");
  await file.save(outputPath);
  return {wb,outputPath};
}

async function buildP06() {
  const metrics = JSON.parse(await fs.readFile(path.join(ROOT,"tmp","quality_metrics.json"),"utf8"));
  const wb=Workbook.create();
  const codigo=wb.worksheets.add("Metricas_Codigo"), hall=wb.worksheets.add("Hallazgos"), plan=wb.worksheets.add("Plan_Mejora"), proceso=wb.worksheets.add("Metricas_Proceso");
  mergeTitle(codigo,"H","P06 · MÉTRICAS DE CALIDAD DEL SOFTWARE","GA2-AA3-EV09 · Medición, interpretación y mejora de Velmorax con evidencia reproducible del código y del proceso.");
  codigo.getRange("A5:H5").values=[["Código","Métrica","Qué mide","Valor referencia","Valor medido","Cumple","Herramienta","Interpretación"]];
  const maxFunc=metrics.max_cyclomatic_function;
  const metRows=[
    ["MET-01","Complejidad ciclomática máxima","Rutas independientes de la función más compleja","≤ 10 por función",metrics.max_cyclomatic,null,"AST Python (script local)",`${maxFunc.file}:${maxFunc.line}, ${maxFunc.name}; requiere separación de decisiones.`],
    ["MET-02","Complejidad cognitiva promedio","Esfuerzo mental promedio para leer funciones","≤ 15 por función",Number(metrics.average_cognitive.toFixed(2)),null,"AST Python (script local)","El promedio es aceptable, aunque existen picos puntuales que sí requieren refactorización."],
    ["MET-03","Cobertura de pruebas","Sentencias Python ejecutadas por la suite","≥ 60%",Number((metrics.statement_coverage*100).toFixed(1))/100,null,"unittest + trace estándar",`${metrics.covered_statement_lines} de ${metrics.statement_lines} sentencias observadas; la suite pasa, pero cubre una parte limitada del sistema.`],
    ["MET-04","Duplicación","Líneas dentro de bloques normalizados repetidos","≤ 3%",Number(metrics.duplication_ratio.toFixed(4)),null,"Detector local de bloques de 6 líneas",`${metrics.duplicate_blocks} bloques repetidos entre archivos; conviene extraer utilidades compartidas.`],
    ["MET-05","Deuda técnica estimada","Esfuerzo correctivo frente a una referencia de 80 h","≤ 5%",0.05,null,"Estimación del plan de mejora","4 h iniciales estimadas / 80 h de referencia; debe actualizarse con tiempos reales."],
    ["MET-06","Incidencias críticas/bloqueantes","Patrones críticos detectados","0",metrics.critical_blocking_issues,null,"AST Python (heurística)","No se detectó eval/exec; esta revisión no sustituye un escáner SAST especializado."],
    ["MET-07","Incidencias mayores","Funciones largas, complejas y capturas amplias","≤ 10",metrics.major_findings_count,null,"AST Python (script local)","El volumen excede la referencia; se deben priorizar los puntos de mayor riesgo y no corregirlos todos a la vez."],
    ["MET-08","Vulnerabilidades de seguridad","Usos directos de eval/exec detectados","0",metrics.security_hits.length,null,"AST Python (heurística)","Sin coincidencias en el alcance revisado; queda pendiente validación con Bandit o SonarQube."],
    ["MET-09","Code smells","Indicadores de mantenibilidad detectados","Tendencia descendente",metrics.code_smells,null,"AST Python (script local)","Se establece una línea base de 39; el siguiente corte debe ser menor."],
    ["MET-10","Líneas de código","Tamaño lógico del código Python analizado","Informativo",metrics.loc,null,"Script local",`${metrics.python_files} archivos Python de app; sirve como contexto, no como calidad por sí sola.`],
    ["MET-11","Acoplamiento interno promedio","Importaciones app.* por archivo","Bajo (≤ 3)",Number(metrics.average_internal_imports.toFixed(2)),null,"AST Python (script local)",`Promedio bajo; el máximo observado es ${metrics.max_internal_imports}, por lo que hay módulos concentradores.`],
    ["MET-12","Cohesión aproximada","Módulos con tamaño e importaciones acotadas","Alta (≥ 70%)",Number(metrics.focused_module_ratio.toFixed(4)),null,"Proxy local documentado",`${metrics.focused_modules} de ${metrics.python_files} módulos cumplen el criterio proxy; queda cerca de la referencia.`],
  ];
  codigo.getRange("A6:H17").values=metRows;
  const complies=["=IF(E6<=10,\"Cumple\",\"No cumple\")","=IF(E7<=15,\"Cumple\",\"No cumple\")","=IF(E8>=60%,\"Cumple\",\"No cumple\")","=IF(E9<=3%,\"Cumple\",\"No cumple\")","=IF(E10<=5%,\"Cumple\",\"No cumple\")","=IF(E11=0,\"Cumple\",\"No cumple\")","=IF(E12<=10,\"Cumple\",\"No cumple\")","=IF(E13=0,\"Cumple\",\"No cumple\")","=\"Línea base\"","=\"Informativo\"","=IF(E16<=3,\"Cumple\",\"No cumple\")","=IF(E17>=70%,\"Cumple\",\"No cumple\")"];
  for(let i=0;i<complies.length;i++) codigo.getRange(`F${6+i}`).formulas=[[complies[i]]];
  codigo.getRange("E8:E10").format.numberFormat="0.0%"; codigo.getRange("E17").format.numberFormat="0.0%";
  tableStyle(codigo,"A5:H17","A5:H5"); codigo.getRange("A6:H17").format.rowHeight=64; setWidths(codigo,{A:10,B:27,C:31,D:20,E:16,F:15,G:27,H:50}); codigo.freezePanes.freezeRows(5);
  codigo.getRange("F6:F17").conditionalFormats.add("expression", { formula: '=$F6="Cumple"', format: { fill: GREEN, font: { color: "#274E13", bold: true } } });
  codigo.getRange("F6:F17").conditionalFormats.add("expression", { formula: '=$F6="No cumple"', format: { fill: RED, font: { color: "#9C0006", bold: true } } });
  codigo.mergeCells("A19:H19"); codigo.getRange("A19").values=[["Alcance y cautela: medición reproducible ejecutada sobre app/**/*.py al 04/09/2026. La cobertura usa unittest + trace, incluida la ejecución en hilos. Las métricas de seguridad, duplicación, acoplamiento y cohesión son heurísticas locales y deben complementarse con SonarQube/Bandit en integración continua."]]; codigo.getRange("A19:H19").format={fill:YELLOW,font:{italic:true,color:"#7F6000"},wrapText:true,verticalAlignment:"center"}; codigo.getRange("A19:H19").format.rowHeight=55;

  mergeTitle(hall,"H","P06 · HALLAZGOS","Resultados concretos de la medición estática y de las pruebas, priorizados por impacto.");
  hall.getRange("A5:H5").values=[["N°","Severidad","Archivo/componente","Descripción","Métrica relacionada","Por qué ocurre","Impacto si no se corrige","Estado"]];
  const findings=[
    [1,"Alta","app/services/network.py:481","fetch_official_veterinary_rows alcanza complejidad ciclomática 23 y cognitiva 52.","MET-01 / MET-02","Concentra consulta, validación, normalización y manejo de alternativas.","Mayor riesgo de defectos y dificultad para probar cambios.","Abierto"],
    [2,"Alta","Suite tests/","La cobertura observada es 33,9%, inferior a la referencia de 60%.","MET-03","Solo existen 5 pruebas de humo para varios módulos funcionales.","Regresiones en citas, pacientes, clínica e inventario pueden pasar inadvertidas.","Abierto"],
    [3,"Media","Código Python de app/","La duplicación estimada es 9,5%, por encima del 3%.","MET-04","Patrones similares de validación, mapeo y respuesta aparecen en distintos archivos.","Correcciones repetidas y divergencia de comportamiento.","Abierto"],
    [4,"Alta","app/routers/web.py y servicios","Se identificaron 39 hallazgos mayores por longitud, complejidad o Exception amplia.","MET-07 / MET-09","El router web y algunos servicios acumularon responsabilidades.","Mantenibilidad reducida y diagnósticos menos precisos.","Abierto"],
    [5,"Media","app/routers/web.py","Cinco capturas amplias de Exception ocultan tipos de error concretos.","MET-07","Se usa manejo genérico para sostener el flujo de interfaz.","Errores reales pueden quedar registrados o tratados de forma insuficiente.","Abierto"],
    [6,"Baja","Proceso de calidad","Antes de este informe no había una línea base consolidada y reproducible.","MET-09","Las mediciones estaban dispersas o no registradas.","No se puede demostrar tendencia ni priorizar mejoras con datos.","Cerrado"],
  ];
  hall.getRange("A6:H11").values=findings; tableStyle(hall,"A5:H11","A5:H5"); hall.getRange("A6:H11").format.rowHeight=72; setWidths(hall,{A:6,B:13,C:29,D:45,E:21,F:42,G:42,H:14}); hall.freezePanes.freezeRows(5); statusFormatting(hall.getRange("H6:H11"));

  mergeTitle(plan,"I","P06 · PLAN DE MEJORA","Acciones alcanzables, responsables y evidencia antes/después. Una acción ya quedó ejecutada en este corte.");
  plan.getRange("A5:I5").values=[["N°","Hallazgo","Acción","Responsable","Fecha compromiso","Estado","Valor antes","Valor después","Evidencia"]];
  const planRows=[
    [1,"H-01 Complejidad de red","Separar consulta, normalización y selección de resultados en funciones pequeñas; agregar pruebas unitarias.","Juan David Bastidas","2026-09-18","Pendiente","CC 23 / cognitiva 52","Meta: CC ≤ 10","app/services/network.py:481"],
    [2,"H-02 Cobertura insuficiente","Agregar pruebas de citas, pacientes, historia clínica e inventario por sede.",TEAM,"2026-09-25","En curso","33,9%","Meta: ≥ 60%","tests/ + Matriz P05 (CP-03 a CP-12)"],
    [3,"H-03 Duplicación","Identificar los bloques repetidos y extraer validadores/mapeadores compartidos sin cambiar comportamiento.","Maicol Andrés Ospina","2026-09-30","Pendiente","9,5%","Meta: ≤ 3%","Reporte del script local"],
    [4,"H-04 Capturas amplias","Sustituir Exception por excepciones esperadas y registrar las inesperadas con contexto.","Juan David Bastidas","2026-10-02","Pendiente","5 capturas amplias","Meta: 0 capturas amplias no justificadas","app/routers/web.py"],
    [5,"H-06 Sin línea base","Crear y ejecutar un script reproducible; documentar 12 métricas, hallazgos y decisiones.",TEAM,"2026-09-04","Ejecutado","Sin medición consolidada","12 métricas y 6 hallazgos registrados","tools/analyze_quality_metrics.py + este libro P06"],
  ];
  plan.getRange("A6:I10").values=planRows; tableStyle(plan,"A5:I10","A5:I5"); plan.getRange("A6:I10").format.rowHeight=76; setWidths(plan,{A:6,B:23,C:48,D:29,E:17,F:14,G:23,H:27,I:40}); plan.freezePanes.freezeRows(5); plan.getRange("F6:F10").dataValidation={rule:{type:"list",values:["Pendiente","En curso","Ejecutado","Bloqueado"]}}; statusFormatting(plan.getRange("F6:F10"));

  mergeTitle(proceso,"E","P06 · MÉTRICAS DEL PROCESO","Lectura del avance documental y de ingeniería disponible en el repositorio al corte.");
  proceso.getRange("A5:E5").values=[["Indicador","Fórmula","Valor","Meta","Análisis"]];
  const proc=[
    ["Historias completadas vs. planificadas","5 implementadas / 5 priorizadas",1,"≥ 80%","Las cinco historias principales modeladas en P03/P04 tienen implementación identificada."],
    ["Puntos por iteración","No existe estimación por puntos",null,"Estable","No medible: definir puntos y cierre por iteración antes del siguiente corte."],
    ["Trazabilidad completa de requisitos","4 cadenas completas / 12 filas",4/12,"≥ 90%","La P05 muestra cobertura parcial por falta de pruebas y modelado complementario."],
    ["Historias con criterios verificados","2 HU con evidencia integral / 6 HU",2/6,"100%","HU-05 y HU-06 tienen evidencia directa; las demás requieren pruebas funcionales dedicadas."],
    ["Defectos posteriores al cierre","No existe registro formal de defectos",null,"Tendencia descendente","No medible: registrar fecha, severidad, causa y versión corregida."],
    ["Commits por integrante","Maicol 2 / Juan David 1",2/3,"Distribución equilibrada","La muestra histórica es pequeña y muestra concentración 66,7% / 33,3%."],
    ["Documentación actualizada con el código","P03, P04, P05 y P06 revisados",1,"100%","Los entregables vigentes describen el flujo veterinario actual y sus brechas."],
  ];
  proceso.getRange("A6:E12").values=proc; proceso.getRange("C6:C12").format.numberFormat="0.0%"; tableStyle(proceso,"A5:E12","A5:E5"); proceso.getRange("A6:E12").format.rowHeight=58; setWidths(proceso,{A:34,B:34,C:17,D:24,E:56}); proceso.freezePanes.freezeRows(5);
  proceso.mergeCells("A14:E14"); proceso.getRange("A14").values=[["Conclusión: el proyecto funciona en los recorridos de humo evaluados (5/5 pruebas), pero necesita ampliar pruebas y reducir complejidad/duplicación. Las prioridades del plan se basan en los valores medidos, no en supuestos de herramienta externa."]]; proceso.getRange("A14:E14").format={fill:SKY,font:{bold:true,color:NAVY},wrapText:true,verticalAlignment:"center"}; proceso.getRange("A14:E14").format.rowHeight=50;

  await fs.mkdir(OUT,{recursive:true});
  const file=await SpreadsheetFile.exportXlsx(wb);
  const outputPath=path.join(OUT,"Maicol_Andres_Ospina_Juan_David_Bastidas_P06_Informe_Metricas_Calidad_Velmorax.xlsx");
  await file.save(outputPath);
  return {wb,outputPath};
}

const p05=await buildP05();
const p06=await buildP06();
for (const [label,item] of [["P05",p05],["P06",p06]]) {
  const overview=await item.wb.inspect({kind:"sheet",include:"id,name",maxChars:3000});
  console.log(label,overview.ndjson);
  const formulas=await item.wb.inspect({kind:"formula",maxChars:6000,options:{maxResults:80}});
  console.log(`${label}_FORMULAS`,formulas.ndjson);
  for (const sheetName of label==="P05"?["Matriz","Huecos","Cobertura","Catálogos"]:["Metricas_Codigo","Hallazgos","Plan_Mejora","Metricas_Proceso"]) {
    const preview=await item.wb.render({sheetName,autoCrop:"all",scale:0.8,format:"png"});
    await fs.writeFile(path.join(OUT,`${label}_${sheetName}.png`),new Uint8Array(await preview.arrayBuffer()));
  }
}
console.log(JSON.stringify({p05:p05.outputPath,p06:p06.outputPath},null,2));
