import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/os/Documents/ChatGPT/velmorax";
const SKILL_DIR = "/Users/os/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const TMP_DIR = path.join(workspaceDir, ".velmorax_evidencias/presentacion_tecnica_build");
const FINAL_PPTX = path.join(workspaceDir, "output/presentaciones_velmorax/Velmorax_Exposicion_Tecnica_Roles_CasosDeUso_Entrega_Final.pptx");
const RUNTIME_PYTHON = "/Users/os/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const { resolvePresentationFont, finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const family = resolvePresentationFont();
const titleFamily = "Georgia";
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });

// Paleta y jerarquía visual inspiradas en la exposición anterior: sobria,
// clínica y muy legible. Las capturas son de la aplicación real local.
const C = { navy: "#183F61", blue: "#226D9C", cyan: "#1CA7AA", sky: "#E7F4F4", ink: "#183448", gray: "#607988", light: "#F5F9FA", line: "#C8DCE1", white: "#FFFFFF", green: "#359B76", orange: "#E47B28", coral: "#D95B5B" };
const shots = {
  clinical: path.join(workspaceDir, "output/evidencias_reales/profesionales/historia-clinica-vista.png"),
  inventory: path.join(workspaceDir, "output/evidencias_reales/02-inventario-lotes-detalle.png"),
  dashboard: path.join(workspaceDir, "output/evidencias_reales/03-tablero-operativo-detalle.png"),
  admin: path.join(workspaceDir, "output/evidencias_reales/profesionales/administracion-vista.png"),
};

function shape(slide, geometry, pos, fill="none", line={fill:"none",width:0}) {
  return slide.shapes.add({ geometry, position:pos, fill, line });
}
function text(slide, value, pos, size=20, color=C.ink, bold=false, opts={}) {
  const s = shape(slide, "textbox", pos, "none", {fill:"none",width:0});
  s.text = value;
  s.text.style = { typeface: family, fontSize:size, color, bold, autoFit:"shrink", ...opts };
  return s;
}
function base(slide, section, num) {
  slide.background.fill = C.light;
  shape(slide, "rect", {left:0,top:0,width:1280,height:16}, C.cyan);
  text(slide, section.toUpperCase(), {left:64,top:44,width:640,height:22}, 13, C.cyan, true, {typeface:titleFamily});
  text(slide, "VELMORAX · FLUJO VETERINARIO", {left:64,top:682,width:340,height:18}, 11, C.gray, false, {typeface:titleFamily});
  text(slide, String(num), {left:1168,top:682,width:48,height:18}, 11, C.gray, false, {typeface:titleFamily,align:"right"});
}
function title(slide, value, subtitle="") {
  text(slide, value, {left:64,top:90,width:1130,height:62}, 38, C.navy, true, {typeface:titleFamily});
  shape(slide,"rect",{left:64,top:163,width:138,height:5},C.cyan);
  if (subtitle) text(slide, subtitle, {left:64,top:181,width:1110,height:27}, 16, C.gray, false);
}
function note(slide, value) { slide.speakerNotes.textFrame.setText(value); slide.speakerNotes.setVisible(true); }
async function addShot(slide, shot, pos, alt) {
  const blob = await fs.readFile(shot);
  slide.images.add({blob, contentType:"image/png", alt, fit:"contain", position:pos, geometry:"roundRect", borderRadius:"rounded-xl"});
  shape(slide,"roundRect",pos,"none",{style:"solid",fill:C.line,width:1});
}
function bullet(slide, heading, body, y, accent=C.blue) {
  shape(slide,"ellipse",{left:68,top:y+4,width:38,height:38},accent);
  text(slide,"•",{left:68,top:y+1,width:38,height:38},25,C.white,true,{align:"center",verticalAlignment:"middle"});
  text(slide,heading,{left:126,top:y,width:370,height:26},19,C.navy,true);
  text(slide,body,{left:126,top:y+30,width:400,height:54},15,C.gray,false);
}
function bulletAt(slide, x, heading, body, y, accent=C.blue) {
  shape(slide,"ellipse",{left:x,top:y+4,width:38,height:38},accent);
  text(slide,"•",{left:x,top:y+1,width:38,height:38},25,C.white,true,{align:"center",verticalAlignment:"middle"});
  text(slide,heading,{left:x+56,top:y,width:370,height:26},19,C.navy,true);
  text(slide,body,{left:x+56,top:y+30,width:400,height:54},15,C.gray,false);
}

// 1
{ const s=p.slides.add(); s.background.fill=C.white;
  shape(s,"rect",{left:0,top:0,width:18,height:720},C.cyan);
  shape(s,"rect",{left:780,top:0,width:500,height:720},C.navy);
  text(s,"VELMORAX",{left:78,top:96,width:250,height:27},16,C.cyan,true,{typeface:titleFamily});
  text(s,"Tecnología que\norganiza la veterinaria",{left:78,top:156,width:655,height:122},46,C.navy,true,{typeface:titleFamily});
  text(s,"Una explicación clara de lo que hace Velmorax y de la tecnología que permite que funcione.",{left:78,top:314,width:615,height:62},22,C.ink,false,{typeface:titleFamily});
  shape(s,"roundRect",{left:78,top:448,width:245,height:40},"#DDF3F2",{fill:"none",width:0});
  text(s,"PROYECTO DE SOFTWARE",{left:101,top:459,width:200,height:16},11,C.cyan,true,{typeface:titleFamily,align:"center"});
  text(s,"Alcance: atención clínica, inventario y administración\nCapturas de la aplicación local con datos de demostración",{left:78,top:565,width:620,height:48},15,C.gray,false);
  text(s,"GESTIÓN VETERINARIA\nEN UNA SOLA PLATAFORMA",{left:830,top:80,width:350,height:52},14,"#8BDCDD",true,{typeface:titleFamily,align:"center"});
  await addShot(s,shots.dashboard,{left:818,top:180,width:385,height:344},"Vista completa del tablero local de Velmorax");
  text(s,"CLÍNICA · INVENTARIO · CONTROL",{left:818,top:580,width:385,height:20},12,"#B5D8E4",true,{typeface:titleFamily,align:"center"});
  note(s,"Guion sugerido: Velmorax ayuda a una clínica veterinaria a organizar pacientes, agenda e insumos desde una sola pantalla. Fuente: aplicación Velmorax ejecutada localmente el 16/09/2026."); }

// 2
{ const s=p.slides.add(); base(s,"Qué hace",2); title(s,"¿Qué hace Velmorax?","Reúne en un solo lugar la información que una clínica necesita para trabajar cada día.");
  bullet(s,"Atención veterinaria","Guarda datos de la mascota, vacunas, controles, consultas y pagos.",226,C.cyan);
  bullet(s,"Insumos","Controla productos, cantidades, fechas de vencimiento y productos con poco stock.",334,C.blue);
  bullet(s,"Administración","Permite organizar sedes, usuarios y las acciones que realiza el equipo.",442,C.green);
  text(s,"La idea principal",{left:620,top:228,width:430,height:28},19,C.navy,true);
  text(s,"El equipo encuentra la información de su sede sin depender de mensajes o papeles separados.",{left:620,top:267,width:470,height:72},24,C.blue,true);
  shape(s,"line",{left:620,top:376,width:480,height:0},"none",{style:"solid",fill:C.cyan,width:3});
  text(s,"En pocas palabras: cuando alguien registra una atención o un producto, el sistema deja ese dato disponible para el resto del equipo autorizado.",{left:620,top:402,width:470,height:86},18,C.gray,false);
  note(s,"Guion sugerido: antes se puede buscar la información en varios lugares. Velmorax la concentra para que el equipo trabaje con el mismo dato. Fuente: README.md y pantallas locales."); }

// 3
{ const s=p.slides.add(); base(s,"Cómo funciona",3); title(s,"Cómo funciona por dentro","La tecnología se divide en pasos simples para llevar una acción de la pantalla hasta la información guardada.");
  const nodes=[
    ["Pantalla web\nLo que ve el equipo",78,250,235,C.sky],
    ["Aplicación\nRecibe cada acción",366,250,220,"#E7F0FB"],
    ["Reglas de trabajo\nEvitan errores",638,250,240,"#EEF7F4"],
    ["Información guardada\nDatos de la clínica",930,250,245,"#F3F0FB"],
  ];
  for (const [label,x,y,w,fill] of nodes) { shape(s,"roundRect",{left:x,top:y,width:w,height:120},fill,{style:"solid",fill:C.line,width:1}); text(s,label,{left:x+16,top:y+29,width:w-32,height:61},20,C.navy,true,{align:"center",verticalAlignment:"middle"}); }
  for (const x of [313,586,888]) { shape(s,"line",{left:x,top:310,width:47,height:0},"none",{style:"solid",fill:C.blue,width:3,beginArrowType:"none",endArrowType:"triangle"}); }
  text(s,"Ejemplo: al guardar una consulta, Velmorax revisa que los datos sean válidos y luego los guarda para consultarlos más adelante.",{left:86,top:448,width:1080,height:64},21,C.gray,false,{align:"center"});
  text(s,"Tecnologías reales: Python, FastAPI, Jinja2, Uvicorn y una base de datos SQLite o PostgreSQL.",{left:115,top:574,width:1040,height:30},17,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: no hace falta explicar los nombres técnicos. Basta decir que la pantalla recibe lo que el usuario registra, Velmorax lo revisa y lo guarda de forma organizada. Fuente: pyproject.toml y app/."); }

// 4
{ const s=p.slides.add(); base(s,"Tecnología",4); title(s,"Tecnología en palabras simples","Cada herramienta tiene una tarea concreta dentro de Velmorax.");
  const rows=[
    ["Python","Es el lenguaje base con el que se programan las reglas de trabajo de Velmorax."],
    ["FastAPI + Uvicorn","Reciben una acción, como guardar un paciente, y entregan una respuesta al navegador."],
    ["Jinja2 + CSS/JS","Construyen las pantallas que usa el personal de la clínica."],
    ["SQLite / PostgreSQL","Guardan pacientes, consultas, inventario, usuarios y movimientos."],
    ["Docker + Caddy","Ayudan a instalar Velmorax en un servidor y a ofrecer una conexión segura por internet."],
    ["Prometheus + Grafana + Loki","Permiten revisar el estado de la aplicación y detectar fallas a tiempo."],
  ];
  let y=210; for (let i=0;i<rows.length;i++,y+=62) { shape(s,"rect",{left:68,top:y,width:13,height:40},i%2?C.cyan:C.blue); text(s,rows[i][0],{left:101,top:y,width:280,height:28},18,C.navy,true); text(s,rows[i][1],{left:405,top:y,width:736,height:42},16,C.gray,false); }
  note(s,"Guion sugerido: presenta la columna de la izquierda como el nombre de la herramienta y la derecha como su utilidad. No es necesario definir cada tecnología. Fuente: pyproject.toml y archivos de despliegue."); }

// 5
{ const s=p.slides.add(); base(s,"Vista real",5); title(s,"Tablero principal","Muestra en un solo lugar lo que está pasando en la clínica durante el día.");
  await addShot(s,shots.dashboard,{left:66,top:205,width:534,height:450},"Captura real del tablero operativo local");
  text(s,"Lo que permite ver",{left:670,top:232,width:410,height:27},21,C.navy,true);
  bulletAt(s,670,"Citas del día","Cuántas personas esperan o están siendo atendidas.",282,C.cyan);
  bulletAt(s,670,"Alertas de productos","Qué insumos necesitan atención porque quedan pocos o están por vencerse.",382,C.blue);
  bulletAt(s,670,"Entrega de turno","Información breve para que el siguiente turno continúe el trabajo.",482,C.green);
  text(s,"Evidencia: ejecución local el 16/09/2026. Los valores visibles corresponden a datos de demostración.",{left:654,top:610,width:490,height:28},13,C.gray,false);
  note(s,"Evidencia primaria: captura creada desde http://127.0.0.1:8000/?organization_id=1&location_id=2 el 16/09/2026. Datos de demostración locales."); }

// 6
{ const s=p.slides.add(); base(s,"Vista real",6); title(s,"Historia de cada paciente","La clínica puede registrar los datos y la atención de cada mascota en un solo lugar.");
  await addShot(s,shots.clinical,{left:66,top:205,width:534,height:450},"Captura real de pacientes y consultas local");
  text(s,"Qué se puede registrar",{left:670,top:228,width:420,height:27},21,C.navy,true);
  bulletAt(s,670,"Datos de la mascota","Especie, raza, peso, vacunas y datos de contacto del responsable.",278,C.cyan);
  bulletAt(s,670,"Atención realizada","Motivo de consulta, diagnóstico, indicaciones y próximo control.",382,C.blue);
  bulletAt(s,670,"Resumen del día","Estado de la atención, forma de pago y opción de sacar reportes.",486,C.green);
  text(s,"La consulta de Max ilustra datos de prueba de la instalación local.",{left:654,top:610,width:480,height:28},13,C.gray,false);
  note(s,"Evidencia primaria: captura creada desde http://127.0.0.1:8000/clinica?organization_id=1&location_id=2 el 16/09/2026. Datos de demostración locales."); }

// 7
{ const s=p.slides.add(); base(s,"Vista real",7); title(s,"Control de insumos","Cada producto se registra con la información necesaria para saber qué hay disponible y qué requiere atención.");
  await addShot(s,shots.inventory,{left:66,top:205,width:534,height:450},"Captura real de inventario local por lotes");
  text(s,"Cómo ayuda al equipo",{left:670,top:227,width:420,height:27},21,C.navy,true);
  bulletAt(s,670,"Datos del producto","Nombre, lote, cantidad disponible y fecha de vencimiento.",276,C.cyan);
  bulletAt(s,670,"Prevención de errores","Evita registrar cantidades negativas o usar productos vencidos o bloqueados.",380,C.blue);
  bulletAt(s,670,"Reposición y traslados","Permite pedir productos y moverlos entre sedes cuando la clínica lo necesita.",498,C.green);
  note(s,"Evidencia primaria: captura creada desde http://127.0.0.1:8000/inventario?organization_id=1&location_id=2 el 16/09/2026. Reglas funcionales documentadas en README.md y app/services/inventory.py."); }

// 8
{ const s=p.slides.add(); base(s,"Protección",8); title(s,"Seguridad de los datos","Velmorax limita quién entra, qué puede ver cada persona y registra las acciones importantes.");
  const cols=[
    ["Clave protegida", "Las contraseñas se guardan de forma protegida y la clave temporal se debe cambiar.", C.cyan],
    ["Cierre automático", "Si una persona deja de usar el sistema, la sesión puede cerrarse para cuidar su acceso.", C.blue],
    ["Permisos", "Cada rol ve solo los módulos y la sede que le corresponden.", C.green],
    ["Conexión segura", "En producción se usa HTTPS para proteger la comunicación entre el navegador y Velmorax.", C.orange],
  ];
  let x=65; for (const [head,body,accent] of cols) { shape(s,"rect",{left:x,top:237,width:245,height:9},accent); text(s,head,{left:x,top:270,width:225,height:30},23,C.navy,true); text(s,body,{left:x,top:318,width:230,height:170},18,C.gray,false); x+=285; }
  shape(s,"line",{left:65,top:560,width:1070,height:0},"none",{style:"solid",fill:C.line,width:1});
  text(s,"Para una instalación real se configuran una clave propia, HTTPS, la base de datos y respaldos periódicos.",{left:88,top:590,width:1040,height:34},19,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: no se trata de memorizar siglas. Lo importante es explicar que Velmorax protege las claves, limita los permisos y usa conexión segura. Fuente: app/core/security.py y configuración de producción."); }

// 9
{ const s=p.slides.add(); base(s,"Instalación",9); title(s,"Cómo llega Velmorax a Internet","La aplicación se publica de forma segura sin exponer directamente la base de datos.");
  const nodes=[
    ["Internet\nConexión segura",74,258,170,C.sky], ["Caddy\nProtege la entrada",307,258,190,"#E7F0FB"], ["Velmorax\nProcesa la información",560,258,190,"#EEF7F4"], ["PostgreSQL\nGuarda los datos",813,258,190,"#F3F0FB"], ["Respaldo\nCopia periódica",1066,258,145,"#FFF4E8"]
  ];
  for (const [lab,x,y,w,fill] of nodes) { shape(s,"roundRect",{left:x,top:y,width:w,height:112},fill,{style:"solid",fill:C.line,width:1}); text(s,lab,{left:x+12,top:y+31,width:w-24,height:50},18,C.navy,true,{align:"center"}); }
  for (const x of [244,497,750,1003]) shape(s,"line",{left:x,top:314,width:60,height:0},"none",{style:"solid",fill:C.blue,width:3,endArrowType:"triangle"});
  text(s,"El sistema revisa que la aplicación y la base de datos estén funcionando. También crea copias para poder recuperar la información si ocurre un problema.",{left:114,top:445,width:1045,height:52},20,C.gray,false,{align:"center"});
  text(s,"El equipo técnico puede revisar alertas y registros para detectar problemas antes de que afecten a los usuarios.",{left:130,top:548,width:1010,height:34},19,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: la aplicación no se conecta a internet de cualquier forma. Primero pasa por una capa de seguridad, guarda los datos y crea respaldos. Fuente: docker-compose.production.yml y deploy/."); }

// 10
{ const s=p.slides.add(); base(s,"Administración",10); title(s,"Administración de la clínica","Esta sección permite organizar el equipo, revisar movimientos importantes y preparar conexiones externas.");
  await addShot(s,shots.admin,{left:66,top:205,width:534,height:450},"Captura real de administración y auditoría local");
  text(s,"Lo que puede administrar",{left:670,top:230,width:420,height:28},21,C.navy,true);
  bulletAt(s,670,"Equipo y sedes","Usuarios, roles y sedes que forman parte de la clínica.",278,C.cyan);
  bulletAt(s,670,"Registro de acciones","Historial de acciones importantes en agenda, productos y alertas.",380,C.blue);
  bulletAt(s,670,"Conexiones externas","Facturación, laboratorio, correo o WhatsApp se activan cuando la clínica las configura.",486,C.green);
  text(s,"Idea final: Velmorax combina funciones clínicas con una base técnica que permite proteger, ordenar y respaldar la información.",{left:659,top:610,width:500,height:42},14,C.gray,false);
  note(s,"Guion sugerido: esta pantalla sirve para organizar la clínica y tener control de lo que ocurre. Las conexiones externas se activan solo si el cliente las necesita. Fuente: captura local del 16/09/2026."); }

// 11
{ const s=p.slides.add(); base(s,"Planificación",11); title(s,"Backlog priorizado","El backlog organiza el trabajo por historias de usuario, prioridad y puntos de historia.");
  const values = [
    ["ID", "Módulo", "Historia o tarea", "Prioridad", "Puntos"],
    ["HU-01", "Acceso", "Inicio de sesión con rol y sede", "Alta", "5"],
    ["HU-02", "Clínica", "Historia por especialidad", "Alta", "8"],
    ["HU-03", "Agenda", "Cita sin conflictos", "Alta", "5"],
    ["HU-04", "Inventario", "Recepción por lote y vencimiento", "Alta", "8"],
    ["HU-05", "Inventario", "Consumo clínico trazable", "Alta", "8"],
    ["HU-06", "Inventario", "Cuarentena y vencimientos", "Alta", "5"],
    ["HU-07", "Administración", "Usuarios, sedes y permisos", "Media", "8"],
    ["HU-08", "Reportes", "Cierres, reportes y auditoría", "Media", "5"],
    ["HT-01", "Técnica", "Persistencia y datos aislados", "Alta", "8"],
    ["HT-02", "Técnica", "Pruebas de reglas críticas", "Alta", "5"],
  ];
  const t = s.tables.add({rows:11,columns:5,left:64,top:222,width:1152,height:362,columnWidths:[98,174,520,190,170],values});
  t.styleOptions = {headerRow:true,bandedRows:true};
  t.borders.assign({style:"solid",fill:C.line,width:1});
  t.cells.block({row:0,column:0,rowCount:1,columnCount:5}).assign({fill:C.navy,textStyle:{typeface:family,fontSize:14,color:C.white,bold:true},margins:{left:10,right:10,top:6,bottom:6}});
  t.cells.block({row:1,column:0,rowCount:10,columnCount:5}).assign({textStyle:{typeface:family,fontSize:13,color:C.ink},margins:{left:10,right:10,top:5,bottom:5}});
  for (let r=1;r<11;r++) {
    t.getCell(r,3).fill = values[r][3] === "Alta" ? "#E7F4F0" : "#F0ECF8";
    t.getCell(r,4).fill = "#EAF2F7";
  }
  text(s,"Primero se priorizan acceso, clínica, agenda e inventario. Las tareas HT-01 y HT-02 sostienen la persistencia y las pruebas de seguridad.",{left:72,top:616,width:1120,height:32},16,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: backlog significa la lista ordenada de trabajo. Cada fila define qué se va a construir, su importancia y un tamaño estimado. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, página 3."); }

// 12
{ const s=p.slides.add(); base(s,"Requisitos",12); title(s,"Historias de usuario y aceptación","Cada historia describe quién necesita algo, qué necesita y cómo se comprueba que funciona.");
  text(s,"Estructura",{left:74,top:230,width:190,height:28},20,C.navy,true);
  text(s,"Como [actor], quiero [acción] para [resultado].",{left:74,top:272,width:500,height:42},22,C.blue,true,{typeface:titleFamily});
  shape(s,"roundRect",{left:74,top:342,width:500,height:220},"#E7F4F4",{style:"solid",fill:C.line,width:1});
  text(s,"HU-04 · Recepción de insumos por lote",{left:103,top:370,width:430,height:28},20,C.navy,true);
  text(s,"Como responsable de inventario, quiero registrar insumos por lote y vencimiento para conocer las existencias que se pueden usar.",{left:103,top:414,width:425,height:54},16,C.gray,false);
  text(s,"Se acepta cuando registra producto, proveedor, lote, cantidad, vencimiento y responsable; crea el movimiento inicial; y evita datos incompletos.",{left:103,top:488,width:425,height:53},16,C.ink,true);
  text(s,"Tres ejemplos que se validan",{left:659,top:230,width:430,height:28},20,C.navy,true);
  const stories = [
    ["HU-01", "Acceso seguro", "Solo muestra las funciones del rol y la sede autorizada.", C.cyan],
    ["HU-05", "Consumo trazable", "Descuenta el saldo y registra el responsable y el lote usado.", C.blue],
    ["HU-06", "Cuarentena", "Bloquea el consumo o traslado de lotes vencidos o no conformes.", C.green],
  ];
  let y=286; for (const [code,head,body,accent] of stories) {
    shape(s,"rect",{left:659,top:y,width:12,height:75},accent);
    text(s,code,{left:692,top:y+2,width:80,height:24},16,accent,true);
    text(s,head,{left:773,top:y,width:310,height:25},19,C.navy,true);
    text(s,body,{left:692,top:y+31,width:425,height:43},16,C.gray,false);
    y+=103;
  }
  text(s,"Criterio de aceptación: una condición visible que demuestra que la historia funciona y que se puede probar.",{left:95,top:616,width:1090,height:30},16,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: no basta con decir que una función existe. Cada historia incluye criterios de aceptación para saber cómo probarla. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, páginas 4 a 6."); }

// 13
{ const s=p.slides.add(); base(s,"Roles",13); title(s,"Roles del sistema","Cada rol trabaja con funciones relacionadas con su responsabilidad y su sede autorizada.");
  const role = (x,y,w,num,name,work,scope,accent) => {
    shape(s,"roundRect",{left:x,top:y,width:w,height:108},C.white,{style:"solid",fill:C.line,width:1});
    shape(s,"ellipse",{left:x+20,top:y+22,width:42,height:42},accent);
    text(s,num,{left:x+20,top:y+31,width:42,height:20},15,C.white,true,{align:"center"});
    text(s,name,{left:x+82,top:y+18,width:w-102,height:25},19,C.navy,true);
    text(s,work,{left:x+82,top:y+47,width:w-102,height:25},15,C.ink,false);
    text(s,"Funciones: "+scope,{left:x+82,top:y+74,width:w-102,height:18},13,C.gray,false);
  };
  role(64,228,536,"01","Administrador de red","Configura el acceso y conserva el control operativo.","sedes, usuarios y permisos",C.navy);
  role(680,228,536,"02","Profesional clínico","Registra y consulta información de la atención.","historia, diagnóstico y consumo",C.cyan);
  role(64,362,536,"03","Responsable de inventario","Controla lo que entra, se vence, se mueve o se repone.","lotes, vencimientos y abastecimiento",C.green);
  role(680,362,536,"04","Personal de recepción","Agenda atenciones sin cruces de horario.","pacientes, propietarios y citas",C.blue);
  role(64,496,1152,"05","Dirección o coordinación","Revisa cierres y decisiones con datos verificables.","reportes, exportaciones y auditoría",C.orange);
  note(s,"Guion sugerido: cada actor tiene un objetivo distinto. Velmorax asigna permisos para que vea las funciones necesarias y no modifique información fuera de su responsabilidad. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, página 2."); }

// 14
{ const s=p.slides.add(); base(s,"Casos de uso",14); title(s,"Casos de uso principales","Un caso de uso describe cómo una persona usa Velmorax para completar una tarea concreta.");
  const useCase = (x,y,accent,actor,head,body) => {
    shape(s,"roundRect",{left:x,top:y,width:542,height:94},C.white,{style:"solid",fill:C.line,width:1});
    shape(s,"rect",{left:x,top:y,width:10,height:94},accent);
    text(s,actor,{left:x+30,top:y+15,width:175,height:18},13,accent,true);
    text(s,head,{left:x+30,top:y+37,width:180,height:44},17,C.navy,true);
    text(s,body,{left:x+230,top:y+26,width:282,height:48},14,C.gray,false);
  };
  useCase(64,232,C.navy,"Usuario autorizado","Acceso y permisos","Inicia sesión y Velmorax muestra el rol y la sede que le corresponden.");
  useCase(674,232,C.cyan,"Profesional clínico","Historia clínica","Registra y consulta una historia por especialidad.");
  useCase(64,352,C.blue,"Personal de recepción","Agendar cita","Valida disponibilidad del profesional y evita cruces de horario.");
  useCase(674,352,C.green,"Inventario","Recepción por lote","Registra producto, lote, vencimiento, cantidad y responsable.");
  useCase(64,472,C.blue,"Profesional clínico","Registrar consumo","Selecciona un lote válido y actualiza existencias con auditoría.");
  useCase(674,472,C.orange,"Dirección","Reportes y auditoría","Consulta cierres y reportes del ámbito permitido.");
  text(s,"El caso CU-01, consumo clínico, se detalla a continuación porque combina atención, inventario, permisos y trazabilidad.",{left:92,top:607,width:1090,height:30},16,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: los casos de uso unen un rol con una tarea dentro del sistema. El listado se basa en RF-01 a RF-08 y en las historias del backlog. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, páginas 2, 3 y 7."); }

// 15
{ const s=p.slides.add(); base(s,"Caso de uso",15); title(s,"Consumo clínico de un lote","Este es el flujo crítico que conecta la atención del paciente con el inventario disponible.");
  const steps = [
    ["1", "Abrir atención", "El profesional inicia la atención y solicita registrar consumo."],
    ["2", "Mostrar lotes", "Velmorax muestra solo lotes de la sede con saldo disponible."],
    ["3", "Elegir cantidad", "El profesional selecciona el lote e ingresa lo utilizado."],
    ["4", "Validar reglas", "Revisa permiso, estado, vencimiento y saldo."],
    ["5", "Registrar movimiento", "Descuenta existencias y crea evidencia de auditoría."],
    ["6", "Confirmar saldo", "Muestra el resultado y el saldo actualizado."],
  ];
  const pos = [[82,235],[448,235],[814,235],[814,435],[448,435],[82,435]];
  steps.forEach(([num,head,body],i) => { const [x,y]=pos[i];
    shape(s,"roundRect",{left:x,top:y,width:290,height:128},i<3?"#E7F4F4":"#EEF4FA",{style:"solid",fill:C.line,width:1});
    shape(s,"ellipse",{left:x+18,top:y+18,width:38,height:38},i<3?C.cyan:C.blue);
    text(s,num,{left:x+18,top:y+22,width:38,height:29},17,C.white,true,{align:"center"});
    text(s,head,{left:x+74,top:y+18,width:190,height:26},18,C.navy,true);
    text(s,body,{left:x+22,top:y+65,width:245,height:45},14,C.gray,false);
  });
  [[372,299,53,0],[738,299,53,0],[959,363,0,47]].forEach(([x,y,w,h]) => shape(s,"line",{left:x,top:y,width:w,height:h},"none",{style:"solid",fill:C.cyan,width:3,endArrowType:"triangle"}));
  shape(s,"line",{left:661,top:499,width:53,height:0},"none",{style:"solid",fill:C.cyan,width:3});
  shape(s,"line",{left:295,top:499,width:53,height:0},"none",{style:"solid",fill:C.cyan,width:3});
  text(s,"Reglas clave: no permite saldo negativo, lotes vencidos o en cuarentena, ni consumo fuera de la sede autorizada.",{left:92,top:612,width:1090,height:31},17,C.blue,true,{align:"center"});
  note(s,"Guion sugerido: este caso de uso muestra por qué el inventario no es solo contar productos. Cada consumo se valida, se registra y queda relacionado con la atención. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, página 7."); }

// 16
{ const s=p.slides.add(); base(s,"Inventario",16); title(s,"Proceso de inventario","Proceso manual frente al proceso validado y trazable con Velmorax.");
  text(s,"AS-IS · Control manual",{left:76,top:230,width:410,height:30},22,C.coral,true,{typeface:titleFamily});
  shape(s,"roundRect",{left:76,top:275,width:500,height:274},"#FCEEEE",{style:"solid",fill:"#F1C7C7",width:1});
  const before = ["Se recibe el insumo y se anota en una hoja de cálculo.","El profesional solicita o toma el producto para la atención.","El consumo se actualiza después, cuando alguien lo recuerda.","Coordinación consolida archivos y responde consultas."];
  let by=306; for (const item of before) { shape(s,"rect",{left:105,top:by+7,width:26,height:5},C.coral); text(s,item,{left:153,top:by,width:370,height:38},16,C.ink,false); by+=57; }
  text(s,"Riesgos: versiones distintas, saldo desactualizado y falta de bloqueo de lotes no utilizables.",{left:101,top:566,width:448,height:45},16,C.coral,true,{align:"center"});
  text(s,"TO-BE · Con Velmorax",{left:694,top:230,width:420,height:30},22,C.green,true,{typeface:titleFamily});
  shape(s,"roundRect",{left:694,top:275,width:500,height:274},"#EAF5EF",{style:"solid",fill:"#C0E0CF",width:1});
  const after = ["Se registra producto, lote, vencimiento, cantidad y proveedor.","El sistema crea el movimiento inicial y calcula la existencia.","El profesional registra consumo desde la atención.","Velmorax valida saldo, sede, vencimiento y cuarentena antes de descontar."];
  let ay=306; for (const item of after) { shape(s,"rect",{left:723,top:ay+7,width:26,height:5},C.green); text(s,item,{left:771,top:ay,width:385,height:38},16,C.ink,false); ay+=57; }
  text(s,"Resultado: una fuente actualizada, alertas y un historial que permite rastrear cada movimiento.",{left:719,top:566,width:448,height:45},16,C.green,true,{align:"center"});
  note(s,"Guion sugerido: AS-IS explica cómo era el proceso manual. TO-BE describe el proceso propuesto con Velmorax. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, página 8."); }

// 17
{ const s=p.slides.add(); base(s,"Calidad",17); title(s,"Calidad, dependencias y cierre","El proyecto no se considera terminado solo porque una pantalla abre: debe cumplir criterios y pruebas.");
  text(s,"Definition of Done",{left:78,top:230,width:430,height:30},23,C.navy,true,{typeface:titleFamily});
  const done = ["La función está implementada y revisada por el equipo.","Los criterios de aceptación, incluso errores, pasan las pruebas.","Se verifican permisos, seguridad y trazabilidad.","La evidencia de prueba y la documentación están actualizadas."];
  let dy=285; for (const item of done) { shape(s,"ellipse",{left:78,top:dy,width:28,height:28},C.green); text(s,"✓",{left:78,top:dy+3,width:28,height:20},16,C.white,true,{align:"center"}); text(s,item,{left:126,top:dy-2,width:430,height:38},17,C.ink,false); dy+=61; }
  text(s,"Dependencias principales",{left:671,top:230,width:430,height:30},23,C.navy,true,{typeface:titleFamily});
  const deps = [
    ["HU-01", "Permite acceso y habilita clínica, agenda, inventario y administración."],
    ["HU-04", "Debe existir antes de consumir o poner en cuarentena un lote."],
    ["HU-05", "Relaciona el consumo con la atención y alimenta reportes."],
    ["HU-08", "Usa movimientos ya registrados para cierres y auditoría."],
  ];
  let py=284; for (const [code,body] of deps) { shape(s,"roundRect",{left:671,top:py,width:84,height:31},"#E7F4F4",{fill:"none",width:0}); text(s,code,{left:681,top:292+(py-284),width:64,height:16},13,C.cyan,true,{align:"center"}); text(s,body,{left:779,top:py-2,width:372,height:39},16,C.ink,false); py+=61; }
  shape(s,"roundRect",{left:78,top:560,width:1070,height:78},C.navy,{fill:"none",width:0});
  text(s,"Velmorax conecta operación clínica, inventario y control técnico con requisitos verificables, permisos y trazabilidad.",{left:118,top:584,width:990,height:31},20,C.white,true,{typeface:titleFamily,align:"center"});
  note(s,"Guion sugerido: Definition of Done significa que una funcionalidad está realmente lista cuando se revisa, se prueba y queda documentada. Las dependencias ayudan a construir en orden. Fuente: Grupo_Velmorax_BacklogHistorias_Entregado.pdf, página 9."); }

const candidatePath = path.join(TMP_DIR, "candidate.pptx");
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const requirements = { explicitTotalSlideCount: 17, requiredNativeTableOwnerSlides: [], requiredNativeChartOwnerSlides: [] };
const result = await finalizePresentation({
  ...requirements, workspaceDir, candidatePath, finalPath: FINAL_PPTX, pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-bullet-geometry","--validate-heading-fit"],
  fontPolicy:{basis:"design",families:[family,titleFamily]}, verifyArtifactToolImport:true,
  receiptPath:path.join(TMP_DIR,"Velmorax_Exposicion_Tecnica_Roles_CasosDeUso_Entrega_Final.validation.json"),
});
console.log(JSON.stringify({finalPath:FINAL_PPTX, result},null,2));
