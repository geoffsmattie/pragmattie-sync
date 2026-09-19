<script setup>
import { reactive, ref, watch } from 'vue'
import { sendJson } from '../api'
import { LEAD_SOURCES } from '../constants'
import { useRepsStore } from '../stores/reps'

const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['saved'])
const reps = useRepsStore()

const blank = () => ({
  first_name: '',
  last_name: '',
  email: '',
  company: '',
  title: '',
  source: 'web',
  score: 50,
  owner_id: null,
})
const form = reactive(blank())
const saving = ref(false)
const error = ref('')
const required = (v) => (v !== null && v !== undefined && String(v).trim() !== '') || 'Required'
const emailRule = (v) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v) || 'Enter a valid email'

watch(open, (isOpen) => {
  if (isOpen) {
    Object.assign(form, blank())
    error.value = ''
    reps.load()
  }
})

async function save(event) {
  const { valid } = await event
  if (!valid) return
  saving.value = true
  error.value = ''
  try {
    const lead = await sendJson('POST', '/api/v1/leads', form)
    emit('saved', lead)
    open.value = false
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="560">
    <v-card title="New lead">
      <v-form @submit.prevent="save">
        <v-card-text>
          <v-row dense>
            <v-col cols="6"><v-text-field v-model="form.first_name" label="First name" :rules="[required]" /></v-col>
            <v-col cols="6"><v-text-field v-model="form.last_name" label="Last name" :rules="[required]" /></v-col>
            <v-col cols="12"><v-text-field v-model="form.email" label="Email" :rules="[required, emailRule]" /></v-col>
            <v-col cols="12"><v-text-field v-model="form.company" label="Company" :rules="[required]" /></v-col>
            <v-col cols="12"><v-text-field v-model="form.title" label="Job title" /></v-col>
            <v-col cols="6"><v-select v-model="form.source" :items="LEAD_SOURCES" label="Source" /></v-col>
            <v-col cols="6">
              <v-select v-model="form.owner_id" :items="reps.options" label="Owner" clearable />
            </v-col>
            <v-col cols="12">
              <div class="text-body-2 text-medium-emphasis">Lead score: {{ form.score }}</div>
              <v-slider v-model="form.score" :min="0" :max="100" :step="1" color="secondary" hide-details />
            </v-col>
          </v-row>
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mt-2">{{ error }}</v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="open = false">Cancel</v-btn>
          <v-btn type="submit" color="primary" variant="flat" :loading="saving">Create lead</v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
