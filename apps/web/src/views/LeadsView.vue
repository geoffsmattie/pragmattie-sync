<script setup>
import { onMounted, ref, watch } from 'vue'
import { getJson, sendJson } from '../api'
import ConvertLeadDialog from '../components/ConvertLeadDialog.vue'
import LeadFormDialog from '../components/LeadFormDialog.vue'
import PageHeader from '../components/PageHeader.vue'
import { LEAD_SOURCES, LEAD_STATUSES, leadStatus } from '../constants'
import { shortDate } from '../format'
import { useRepsStore } from '../stores/reps'

const reps = useRepsStore()
const headers = [
  { title: 'Name', key: 'last_name' },
  { title: 'Company', key: 'company' },
  { title: 'Source', key: 'source', sortable: false },
  { title: 'Status', key: 'status' },
  { title: 'Score', key: 'score', align: 'end' },
  { title: 'Owner', key: 'owner', sortable: false },
  { title: 'Created', key: 'created_at', align: 'end' },
  { title: '', key: 'actions', sortable: false, align: 'end' },
]

const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const search = ref('')
const statusFilter = ref(['new', 'working', 'qualified'])
const sourceFilter = ref(null)
const ownerFilter = ref(null)
const options = ref({ page: 1, itemsPerPage: 25, sortBy: [{ key: 'created_at', order: 'desc' }] })
const showCreate = ref(false)
const converting = ref(null)
const showConvert = ref(false)
const snack = ref('')

async function load() {
  loading.value = true
  error.value = ''
  const { page, itemsPerPage, sortBy } = options.value
  const sort = sortBy[0] ? `${sortBy[0].order === 'desc' ? '-' : ''}${sortBy[0].key}` : '-created_at'
  try {
    const data = await getJson('/api/v1/leads', {
      q: search.value,
      status: statusFilter.value,
      source: sourceFilter.value,
      owner_id: ownerFilter.value,
      sort,
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
  timer = setTimeout(() => {
    options.value = { ...options.value, page: 1 }
  }, 300)
})
watch([statusFilter, sourceFilter, ownerFilter], () => {
  options.value = { ...options.value, page: 1 }
})
watch(options, load, { deep: true })
onMounted(() => {
  reps.load()
  load()
})

async function setStatus(lead, status) {
  try {
    await sendJson('PATCH', `/api/v1/leads/${lead.id}`, { status })
    snack.value = `${lead.first_name} ${lead.last_name} marked ${leadStatus(status).title.toLowerCase()}`
    load()
  } catch (err) {
    error.value = err.message
  }
}

function startConvert(lead) {
  converting.value = lead
  showConvert.value = true
}

function onCreated(lead) {
  snack.value = `Lead created for ${lead.company}`
  load()
}
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader title="Leads" subtitle="Inbound and outbound interest, scored and assigned to reps.">
      <v-btn color="primary" prepend-icon="mdi-plus" @click="showCreate = true">New lead</v-btn>
    </PageHeader>

    <v-card>
      <v-card-text class="d-flex flex-wrap ga-3 align-center">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          placeholder="Search name, company or email"
          density="compact"
          hide-details
          clearable
          style="min-width: 280px; max-width: 340px"
        />
        <v-chip-group v-model="statusFilter" multiple selected-class="text-secondary" column>
          <v-chip v-for="s in LEAD_STATUSES" :key="s.value" :value="s.value" filter variant="outlined" size="small">
            {{ s.title }}
          </v-chip>
        </v-chip-group>
        <v-spacer />
        <v-select
          v-model="sourceFilter"
          :items="LEAD_SOURCES"
          label="Source"
          density="compact"
          hide-details
          clearable
          style="max-width: 160px"
        />
        <v-select
          v-model="ownerFilter"
          :items="reps.options"
          label="Owner"
          density="compact"
          hide-details
          clearable
          style="max-width: 200px"
        />
      </v-card-text>

      <v-alert v-if="error" type="error" variant="tonal" class="mx-4 mb-2">{{ error }}</v-alert>

      <v-data-table-server
        v-model:options="options"
        :headers="headers"
        :items="items"
        :items-length="total"
        :loading="loading"
        :items-per-page="options.itemsPerPage"
        :items-per-page-options="[10, 25, 50, 100]"
        hover
      >
        <template #[`item.last_name`]="{ item }">
          <div class="font-weight-medium">{{ item.first_name }} {{ item.last_name }}</div>
          <div class="text-caption text-medium-emphasis">{{ item.title }}</div>
        </template>
        <template #[`item.company`]="{ item }">
          <div>{{ item.company }}</div>
          <div class="text-caption text-medium-emphasis">{{ item.email }}</div>
        </template>
        <template #[`item.source`]="{ item }">
          <span class="text-capitalize">{{ item.source }}</span>
        </template>
        <template #[`item.status`]="{ item }">
          <v-chip :color="leadStatus(item.status).color" :prepend-icon="leadStatus(item.status).icon" size="small" label>
            {{ leadStatus(item.status).title }}
          </v-chip>
        </template>
        <template #[`item.score`]="{ item }">
          <div class="d-flex align-center justify-end ga-2">
            <v-progress-linear
              :model-value="item.score"
              color="secondary"
              bg-color="secondary"
              rounded
              height="6"
              style="width: 60px"
            />
            <span class="text-body-2" style="width: 24px">{{ item.score }}</span>
          </div>
        </template>
        <template #[`item.owner`]="{ item }">{{ item.owner?.name ?? 'Unassigned' }}</template>
        <template #[`item.created_at`]="{ item }"><span class="text-no-wrap">{{ shortDate(item.created_at) }}</span></template>
        <template #[`item.actions`]="{ item }">
          <template v-if="item.status === 'converted'">
            <v-btn
              size="small"
              variant="text"
              :to="{ name: 'account', params: { id: item.converted_account_id } }"
              append-icon="mdi-arrow-right"
            >
              Account
            </v-btn>
          </template>
          <template v-else>
            <v-menu>
              <template #activator="{ props }">
                <v-btn v-bind="props" icon="mdi-dots-vertical" size="small" variant="text" aria-label="Lead actions" />
              </template>
              <v-list density="compact">
                <v-list-item
                  v-if="item.status !== 'disqualified'"
                  prepend-icon="mdi-swap-horizontal"
                  title="Convert to account"
                  @click="startConvert(item)"
                />
                <v-list-item
                  v-for="s in LEAD_STATUSES.filter((x) => x.value !== item.status && x.value !== 'converted')"
                  :key="s.value"
                  :prepend-icon="s.icon"
                  :title="`Mark ${s.title.toLowerCase()}`"
                  @click="setStatus(item, s.value)"
                />
              </v-list>
            </v-menu>
          </template>
        </template>
      </v-data-table-server>
    </v-card>

    <LeadFormDialog v-model="showCreate" @saved="onCreated" />
    <ConvertLeadDialog v-model="showConvert" :lead="converting" />
    <v-snackbar :model-value="!!snack" color="primary" timeout="3000" @update:model-value="snack = ''">{{ snack }}</v-snackbar>
  </v-container>
</template>
