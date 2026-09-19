<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getJson } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { INDUSTRIES } from '../constants'
import { money, moneyFull } from '../format'
import { useRepsStore } from '../stores/reps'

const router = useRouter()
const reps = useRepsStore()
const headers = [
  { title: 'Account', key: 'name', sortable: false },
  { title: 'Industry', key: 'industry', sortable: false },
  { title: 'Region', key: 'region', sortable: false },
  { title: 'Employees', key: 'employee_count', align: 'end', sortable: false },
  { title: 'Contacts', key: 'contact_count', align: 'end', sortable: false },
  { title: 'Open pipeline', key: 'open_pipeline', align: 'end', sortable: false },
  { title: 'Owner', key: 'owner', sortable: false },
]

const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const search = ref('')
const industry = ref(null)
const owner = ref(null)
const options = ref({ page: 1, itemsPerPage: 25 })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { page, itemsPerPage } = options.value
    const data = await getJson('/api/v1/accounts', {
      q: search.value,
      industry: industry.value,
      owner_id: owner.value,
      limit: itemsPerPage,
      offset: (page - 1) * itemsPerPage,
    })
    items.value = data.items
    total.value = data.total
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

let timer
watch(search, () => {
  clearTimeout(timer)
  timer = setTimeout(() => (options.value = { ...options.value, page: 1 }), 300)
})
watch([industry, owner], () => (options.value = { ...options.value, page: 1 }))
watch(options, load, { deep: true })
onMounted(() => {
  reps.load()
  load()
})

const openAccount = (_event, { item }) => router.push({ name: 'account', params: { id: item.id } })
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader title="Accounts" subtitle="Customer and prospect companies, with their open pipeline." />
    <v-card>
      <v-card-text class="d-flex flex-wrap ga-3 align-center">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          placeholder="Search accounts"
          density="compact"
          hide-details
          clearable
          style="max-width: 320px"
        />
        <v-spacer />
        <v-select v-model="industry" :items="INDUSTRIES" label="Industry" density="compact" hide-details clearable style="max-width: 220px" />
        <v-select v-model="owner" :items="reps.options" label="Owner" density="compact" hide-details clearable style="max-width: 200px" />
      </v-card-text>
      <v-alert v-if="error" type="error" variant="tonal" class="mx-4 mb-2">{{ error }}</v-alert>
      <v-data-table-server
        v-model:options="options"
        :headers="headers"
        :items="items"
        :items-length="total"
        :loading="loading"
        :items-per-page="options.itemsPerPage"
        hover
        class="clickable-rows"
        @click:row="openAccount"
      >
        <template #[`item.name`]="{ item }">
          <span class="font-weight-medium">{{ item.name }}</span>
        </template>
        <template #[`item.employee_count`]="{ item }">{{ item.employee_count.toLocaleString() }}</template>
        <template #[`item.open_pipeline`]="{ item }">
          <span :title="moneyFull(item.open_pipeline)">{{ Number(item.open_pipeline) ? money(item.open_pipeline) : '—' }}</span>
        </template>
        <template #[`item.owner`]="{ item }">{{ item.owner?.name ?? 'Unassigned' }}</template>
      </v-data-table-server>
    </v-card>
  </v-container>
</template>

<style scoped>
.clickable-rows :deep(tbody tr) {
  cursor: pointer;
}
</style>
