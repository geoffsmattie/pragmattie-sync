<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { sendJson } from '../api'
import { INDUSTRIES, REGIONS } from '../constants'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ lead: { type: Object, default: null } })
const emit = defineEmits(['converted'])
const router = useRouter()

const form = reactive({})
const saving = ref(false)
const error = ref('')

watch(open, (isOpen) => {
  if (!isOpen || !props.lead) return
  error.value = ''
  Object.assign(form, {
    industry: 'Technology',
    region: 'North America East',
    employee_count: 100,
    create_opportunity: true,
    opportunity_name: `${props.lead.company} - New business`,
    opportunity_amount: 25000,
  })
})

async function convert() {
  saving.value = true
  error.value = ''
  try {
    const body = {
      industry: form.industry,
      region: form.region,
      employee_count: Number(form.employee_count),
      ...(form.create_opportunity
        ? { opportunity_name: form.opportunity_name, opportunity_amount: Number(form.opportunity_amount) }
        : {}),
    }
    const result = await sendJson('POST', `/api/v1/leads/${props.lead.id}/convert`, body)
    emit('converted', result)
    open.value = false
    router.push({ name: 'account', params: { id: result.account_id } })
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="520">
    <v-card v-if="lead" :title="`Convert ${lead.first_name} ${lead.last_name}`">
      <v-card-subtitle>Creates an account for {{ lead.company }} with this person as a contact.</v-card-subtitle>
      <v-card-text>
        <v-row dense>
          <v-col cols="6"><v-select v-model="form.industry" :items="INDUSTRIES" label="Industry" /></v-col>
          <v-col cols="6"><v-select v-model="form.region" :items="REGIONS" label="Region" /></v-col>
          <v-col cols="12">
            <v-text-field v-model="form.employee_count" type="number" label="Employees" min="1" />
          </v-col>
          <v-col cols="12">
            <v-switch v-model="form.create_opportunity" color="secondary" label="Also create an opportunity" hide-details />
          </v-col>
          <template v-if="form.create_opportunity">
            <v-col cols="12"><v-text-field v-model="form.opportunity_name" label="Opportunity name" /></v-col>
            <v-col cols="12">
              <v-text-field v-model="form.opportunity_amount" type="number" label="Amount (USD)" prefix="$" min="1" />
            </v-col>
          </template>
        </v-row>
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mt-2">{{ error }}</v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="open = false">Cancel</v-btn>
        <v-btn color="primary" variant="flat" :loading="saving" @click="convert">Convert lead</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
