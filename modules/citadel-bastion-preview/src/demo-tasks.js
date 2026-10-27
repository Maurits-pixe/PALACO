export async function readDemoTasks(fetchImpl = globalThis.fetch) {
  const response = await fetchImpl('/api/tasks', { credentials: 'omit', signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error('Demo read failed');
  const tasks = await response.json();
  if (!Array.isArray(tasks) || !tasks.every(task => typeof task.id === 'string'
    && typeof task.title === 'string' && typeof task.description === 'string')) throw new Error('Invalid tasks');
  return tasks;
}
