import { ref, onUnmounted } from 'vue'
import { request } from '../api/client'

export function useRunEvents() {
  const status = ref('input'), report = ref(null), error = ref(''), tasks = ref([])
  const receivedVerdicts = ref([]), reconnecting = ref(false)
  let source, generation = 0, finishing = false
  function disconnect() { source?.close(); source = null }
  function clear() {
    generation++; disconnect(); finishing = false
    status.value = 'input'; report.value = null; error.value = ''; tasks.value = []
    receivedVerdicts.value = []; reconnecting.value = false
  }
  async function finish(id, token) {
    if (finishing) return
    finishing = true
    try {
      const result = await request(`/api/runs/${id}`)
      if (token !== generation) return
      report.value = result.report
      tasks.value = result.report?.tasks ?? tasks.value
      status.value = result.status === 'failed' ? 'failed' : 'done'
      if (status.value === 'failed' && !error.value) error.value = '검토가 실패했습니다. 작업 내역을 확인해 주세요.'
    } catch (e) {
      if (token === generation) { error.value = e.message; status.value = 'failed' }
    } finally {
      if (token === generation) { disconnect(); reconnecting.value = false; finishing = false }
    }
  }
  async function start(payload) {
    clear()
    const token = generation
    status.value = 'running'
    try {
      const { run_id: id } = await request('/api/runs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      if (token !== generation) return
      source = new EventSource(`/api/runs/${id}/events`)
      source.onopen = () => { reconnecting.value = false }
      source.addEventListener('stage', event => {
        if (token !== generation) return
        const task = JSON.parse(event.data)
        const index = tasks.value.findIndex(t => t.task_id === task.task_id)
        if (index < 0) tasks.value.push(task)
        else tasks.value[index] = task
      })
      source.addEventListener('verdict', event => {
        const verdict = JSON.parse(event.data)
        const index = receivedVerdicts.value.findIndex(v => v.id === verdict.id)
        if (index < 0) receivedVerdicts.value.push(verdict)
        else receivedVerdicts.value[index] = verdict
      })
      source.addEventListener('error', async event => {
        if (token !== generation) return
        if (event.data) { error.value = JSON.parse(event.data).message; return }
        reconnecting.value = true
        // 서버 재시작으로 run이 사라지면 재연결 루프를 종료한다.
        try {
          const result = await request(`/api/runs/${id}`)
          if (token === generation && result.status !== 'running') await finish(id, token)
        } catch (e) {
          if (token === generation) { error.value = e.message; status.value = 'failed'; disconnect() }
        }
      })
      source.addEventListener('done', () => finish(id, token))
    } catch (e) {
      if (token === generation) { error.value = e.message; status.value = 'failed' }
    }
  }
  onUnmounted(() => { generation++; disconnect() })
  return { status, report, error, tasks, receivedVerdicts, reconnecting, start, clear }
}
