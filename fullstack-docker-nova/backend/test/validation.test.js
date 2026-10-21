import assert from 'node:assert/strict';
import test from 'node:test';

process.env.DB_HOST = 'database';
process.env.DB_NAME = 'test';
process.env.DB_USER = 'test';
process.env.DB_PASSWORD = 'test';
process.env.NODE_ENV = 'test';

const { validId, validTask, validTaskUpdate } = await import('../src/index.js');

test('normaliza una tarea válida', () => {
  assert.deepEqual(validTask({ title: '  probar el frontend  ' }), { title: 'probar el frontend' });
});

test('rechaza títulos vacíos y mayores a 255 caracteres', () => {
  assert.equal(validTask({ title: '' }), null);
  assert.equal(validTask({ title: ' '.repeat(4) }), null);
  assert.equal(validTask({ title: 'a'.repeat(256) }), null);
});

test('valida el identificador y el cuerpo de actualización', () => {
  assert.equal(validId('5'), 5);
  assert.equal(validId('-1'), null);
  assert.deepEqual(
    validTaskUpdate({ title: '  finalizar interfaz ', completed: false }),
    { title: 'finalizar interfaz', completed: false },
  );
  assert.equal(validTaskUpdate({ title: 'finalizar interfaz' }), null);
});
