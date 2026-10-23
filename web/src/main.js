import { createApp } from 'vue';
import App from './App.vue';
// Radix UI Colors 色阶：中性色 slate、语义色 green/red/amber、代码高亮 purple
import '@radix-ui/colors/slate.css';
import '@radix-ui/colors/slate-alpha.css';
import '@radix-ui/colors/green.css';
import '@radix-ui/colors/red.css';
import '@radix-ui/colors/amber.css';
import '@radix-ui/colors/purple.css';
import './styles.css';

createApp(App).mount('#root');
