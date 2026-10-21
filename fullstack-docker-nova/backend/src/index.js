import 'dotenv/config';
import cors from 'cors';
import express from 'express';
import mysql from 'mysql2/promise';

export const app = express();

app.use(cors());
app.use(express.json());

const requiredVariables = ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD'];
const missingVariables = requiredVariables.filter((variable) => !process.env[variable]);

if (missingVariables.length > 0) {
  throw new Error(`Faltan variables de base de datos: ${missingVariables.join(', ')}`);
}

export const pool = mysql.createPool({
  host: process.env.DB_HOST,
  port: Number(process.env.DB_PORT || 3306),
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
  waitForConnections: true,
  connectionLimit: 10,
});

export function validTask(payload = {}) {
  const title = String(payload.title || '').trim();
  return title.length > 0 && title.length <= 255 ? { title } : null;
}

export function validId(value) {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function validTaskUpdate(payload = {}) {
  const task = validTask(payload);
  return task && typeof payload.completed === 'boolean'
    ? { ...task, completed: payload.completed }
    : null;
}

app.get('/api/health', async (_request, response) => {
  try {
    await pool.query('SELECT 1');
    response.json({ status: 'ok', db: 'connected' });
  } catch (error) {
    console.error('No fue posible verificar la base de datos.', error);
    response.status(500).json({ status: 'error', db: 'disconnected' });
  }
});

app.get('/api/tasks', async (_request, response, next) => {
  try {
    const [tasks] = await pool.query(
      'SELECT id, title, completed, created_at FROM task ORDER BY id DESC',
    );
    response.json(tasks);
  } catch (error) {
    next(error);
  }
});

app.post('/api/tasks', async (request, response, next) => {
  const task = validTask(request.body);

  if (!task) {
    return response.status(400).json({ error: 'El título de la tarea es obligatorio y debe tener máximo 255 caracteres.' });
  }

  try {
    const [result] = await pool.execute('INSERT INTO task (title) VALUES (?)', [task.title]);
    response.status(201).json({ id: result.insertId, ...task, completed: false });
  } catch (error) {
    next(error);
  }
});

app.put('/api/tasks/:id', async (request, response, next) => {
  const id = validId(request.params.id);
  const task = validTaskUpdate(request.body);

  if (!id) return response.status(400).json({ error: 'El identificador de la tarea es inválido.' });
  if (!task) return response.status(400).json({ error: 'Envía un título válido y el estado completado de la tarea.' });

  try {
    const [result] = await pool.execute(
      'UPDATE task SET title = ?, completed = ? WHERE id = ?',
      [task.title, task.completed, id],
    );

    if (!result.affectedRows) return response.status(404).json({ error: 'La tarea no existe.' });

    response.json({ id, ...task });
  } catch (error) {
    next(error);
  }
});

app.delete('/api/tasks/:id', async (request, response, next) => {
  const id = validId(request.params.id);

  if (!id) return response.status(400).json({ error: 'El identificador de la tarea es inválido.' });

  try {
    const [result] = await pool.execute('DELETE FROM task WHERE id = ?', [id]);

    if (!result.affectedRows) return response.status(404).json({ error: 'La tarea no existe.' });

    response.status(204).end();
  } catch (error) {
    next(error);
  }
});

app.use((error, _request, response, _next) => {
  console.error('Error en la API.', error);
  response.status(500).json({ error: 'No fue posible completar la operación.' });
});

if (process.env.NODE_ENV !== 'test') {
  const port = Number(process.env.PORT || 3000);
  app.listen(port, () => console.log(`API disponible en el puerto ${port}`));
}
