import { useCallback, useEffect, useState } from 'react';

export default function TaskList() {
  const [tasks, setTasks] = useState([]);
  const [title, setTitle] = useState('');
  const [editingTask, setEditingTask] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState('');

  const loadTasks = useCallback(async () => {
    setIsLoading(true);

    try {
      const response = await fetch('/api/tasks');
      const data = await response.json();

      if (!response.ok) throw new Error(data.error || 'No fue posible cargar las tareas.');

      setTasks(data);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  function resetEditor() {
    setTitle('');
    setEditingTask(null);
  }

  function startEditing(task) {
    setTitle(task.title);
    setEditingTask(task);
    setMessage(`Editando: ${task.title}`);
  }

  async function saveTask(event) {
    event.preventDefault();
    const taskTitle = title.trim();

    if (!taskTitle) {
      setMessage('Escribe una tarea antes de guardarla.');
      return;
    }

    setIsSubmitting(true);
    setMessage('');

    try {
      const response = await fetch(
        editingTask ? `/api/tasks/${editingTask.id}` : '/api/tasks',
        {
          method: editingTask ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            editingTask
              ? { title: taskTitle, completed: Boolean(editingTask.completed) }
              : { title: taskTitle },
          ),
        },
      );
      const data = response.status === 204 ? null : await response.json();

      if (!response.ok) throw new Error(data?.error || 'No fue posible guardar la tarea.');

      const action = editingTask ? 'actualizada' : 'agregada';
      resetEditor();
      setMessage(`Tarea ${action}.`);
      await loadTasks();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function toggleTask(task) {
    setIsSubmitting(true);
    setMessage('');

    try {
      const response = await fetch(`/api/tasks/${task.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: task.title, completed: !Boolean(task.completed) }),
      });
      const data = await response.json();

      if (!response.ok) throw new Error(data.error || 'No fue posible actualizar la tarea.');

      setMessage(task.completed ? 'Tarea devuelta a pendientes.' : 'Tarea marcada como hecha.');
      await loadTasks();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function deleteTask(task) {
    if (!window.confirm(`¿Eliminar la tarea “${task.title}”?`)) return;

    setIsSubmitting(true);
    setMessage('');

    try {
      const response = await fetch(`/api/tasks/${task.id}`, { method: 'DELETE' });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'No fue posible eliminar la tarea.');
      }

      if (editingTask?.id === task.id) resetEditor();
      setMessage('Tarea eliminada.');
      await loadTasks();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="workspace" aria-labelledby="workspace-title">
      <div className="workspace-topline">
        <p id="workspace-title">Lista activa</p>
        <span>{tasks.length.toString().padStart(2, '0')} registros</span>
      </div>

      <form className="composer" onSubmit={saveTask}>
        <label htmlFor="title">{editingTask ? 'Editar tarea' : '¿Qué sigue?'}</label>
        <div className="composer-row">
          <input
            id="title"
            name="title"
            maxLength="255"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Ej. preparar el despliegue"
            required
          />
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Guardando…' : editingTask ? 'Guardar' : 'Añadir'}
          </button>
          {editingTask && (
            <button className="cancel-edit" type="button" onClick={resetEditor} disabled={isSubmitting}>Cancelar</button>
          )}
        </div>
      </form>

      <p className="message" role="status">{message}</p>

      {isLoading ? (
        <p className="empty">Recuperando la lista…</p>
      ) : tasks.length === 0 ? (
        <p className="empty">La lista está vacía. Crea la primera tarea.</p>
      ) : (
        <ol className="tasks" aria-live="polite">
          {tasks.map((task, index) => (
            <li key={task.id} className={task.completed ? 'completed' : ''}>
              <span className="task-number">{String(index + 1).padStart(2, '0')}</span>
              <span className="task-title">{task.title}</span>
              <div className="row-actions">
                <button
                  type="button"
                  className="state"
                  onClick={() => toggleTask(task)}
                  disabled={isSubmitting}
                  aria-label={task.completed ? `Marcar ${task.title} como pendiente` : `Marcar ${task.title} como hecha`}
                >
                  {task.completed ? 'Hecha' : 'Pendiente'}
                </button>
                <button type="button" className="edit-task" onClick={() => startEditing(task)} disabled={isSubmitting}>Editar</button>
                <button type="button" className="delete-task" onClick={() => deleteTask(task)} disabled={isSubmitting}>Eliminar</button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
