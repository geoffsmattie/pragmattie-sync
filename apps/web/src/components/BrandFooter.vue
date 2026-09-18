<script setup>
import logo from '../assets/pragmattie-logo.jpg'
</script>

<template>
  <v-footer class="brand-footer" border>
    <span class="text-medium-emphasis text-body-2">
      SyncVista is a fictional company. Demo by
    </span>
    <img :src="logo" alt="PragMattie Growth Partners, LLC" class="brand-logo" />
  </v-footer>
</template>

<style scoped>
.brand-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}
.brand-logo {
  height: 34px;
}
</style>
