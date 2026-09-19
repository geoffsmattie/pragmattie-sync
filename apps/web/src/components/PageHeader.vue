<script setup>
defineProps({ title: { type: String, required: true }, subtitle: { type: String, default: '' } })
</script>

<template>
  <div class="d-flex align-center flex-wrap ga-4 mb-6">
    <div class="flex-grow-1">
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="text-body-2 text-medium-emphasis mt-1">{{ subtitle }}</p>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.page-title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}
</style>
