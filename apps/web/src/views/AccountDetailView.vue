<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJson } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { stageTitle } from '../constants'
import { money, moneyFull, shortDate } from '../format'

const props = defineProps({ id: { type: [String, Number], required: true } })
const account = ref(null)
const error = ref('')

async function load() {
  error.value = ''
  try {
    account.value = await getJson(`/api/v1/accounts/${props.id}`)
  } catch (err) {
    error.value = err.message
  }
}
watch(() => props.id, load)
onMounted(load)

const openOpps = computed(() =>
  (account.value?.opportunities ?? []).filter((o) => !o.stage.startsWith('closed')),
)
const wonTotal = computed(() =>
  (account.value?.opportunities ?? [])
    .filter((o) => o.stage === 'closed_won')
    .reduce((sum, o) => sum + Number(o.amount), 0),
)
const oppHeaders = [
  { title: 'Opportunity', key: 'name' },
  { title: 'Stage', key: 'stage' },
  { title: 'Amount', key: 'amount', align: 'end' },
  { title: 'Close date', key: 'close_date', align: 'end' },
  { title: 'Owner', key: 'owner' },
]
</script>

<template>
  <v-container fluid class="pa-6">
    <v-btn variant="text" prepend-icon="mdi-arrow-left" :to="{ name: 'accounts' }" class="mb-2 ml-n3">Accounts</v-btn>
    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
    <template v-if="account">
      <PageHeader :title="account.name" :subtitle="`${account.industry} · ${account.region}`">
        <v-btn v-if="account.website" :href="account.website" target="_blank" variant="text" append-icon="mdi-open-in-new">
          Website
        </v-btn>
      </PageHeader>

      <v-row class="mb-2">
        <v-col v-for="tile in [
          { label: 'Open pipeline', value: money(account.open_pipeline) },
          { label: 'Open deals', value: openOpps.length },
          { label: 'Closed won (all time)', value: money(wonTotal) },
          { label: 'Employees', value: account.employee_count.toLocaleString() },
        ]" :key="tile.label" cols="6" md="3">
          <v-card class="pa-4">
            <div class="text-body-2 text-medium-emphasis">{{ tile.label }}</div>
            <div class="kpi-value mt-1">{{ tile.value }}</div>
          </v-card>
        </v-col>
      </v-row>

      <v-row>
        <v-col cols="12" lg="8">
          <v-card title="Opportunities">
            <v-data-table :headers="oppHeaders" :items="account.opportunities" density="comfortable" items-per-page="10">
              <template #[`item.stage`]="{ item }">
                <v-chip size="small" label :color="item.stage === 'closed_won' ? 'success' : item.stage === 'closed_lost' ? 'grey' : 'secondary'">
                  {{ stageTitle(item.stage) }}
                </v-chip>
              </template>
              <template #[`item.amount`]="{ item }">{{ moneyFull(item.amount) }}</template>
              <template #[`item.close_date`]="{ item }">{{ shortDate(item.close_date) }}</template>
              <template #[`item.owner`]="{ item }">{{ item.owner?.name ?? '—' }}</template>
            </v-data-table>
          </v-card>
        </v-col>
        <v-col cols="12" lg="4">
          <v-card title="Contacts">
            <v-list lines="three" density="compact">
              <v-list-item v-for="c in account.contacts" :key="c.id" :title="`${c.first_name} ${c.last_name}`">
                <v-list-item-subtitle>{{ c.title }}</v-list-item-subtitle>
                <v-list-item-subtitle>{{ c.email }}</v-list-item-subtitle>
                <v-list-item-subtitle>{{ c.phone }}</v-list-item-subtitle>
              </v-list-item>
              <v-list-item v-if="!account.contacts.length" title="No contacts yet" />
            </v-list>
          </v-card>
          <v-card class="mt-4" title="Details">
            <v-list density="compact">
              <v-list-item title="Owner" :subtitle="account.owner?.name ?? 'Unassigned'" />
              <v-list-item title="Annual revenue" :subtitle="moneyFull(account.annual_revenue)" />
              <v-list-item title="Customer since" :subtitle="shortDate(account.created_at)" />
            </v-list>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </v-container>
</template>
