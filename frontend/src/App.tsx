import { useQuery } from '@tanstack/react-query';

import { api } from './lib/api';
import { useStore } from './state/store';
import { AnalysisDrawer } from './components/AnalysisDrawer';
import { ErrorSheet } from './components/ErrorSheet';
import { LayerPanel } from './components/LayerPanel';
import { MapCanvas } from './components/MapCanvas';
import { SidePanel } from './components/SidePanel';
import { TabBar } from './components/TabBar';
import { TopBar } from './components/TopBar';
import './App.css';

export function App() {
  const panelOpen = useStore((s) => s.panelOpen);
  const layersOpen = useStore((s) => s.layersOpen);

  // Fetched once and shared: the data-mode indicator, limits and layer
  // catalogue drive several panels.
  const status = useQuery({ queryKey: ['status'], queryFn: api.status });
  const layers = useQuery({ queryKey: ['layers'], queryFn: api.layers });

  return (
    <div
      className="app"
      data-panel={panelOpen ? 'open' : 'closed'}
      data-layers={layersOpen ? 'open' : 'closed'}
    >
      <TopBar status={status.data} isLoading={status.isLoading} error={status.error} />

      <main className="app__map" aria-label="Map workspace">
        <MapCanvas />
        <LayerPanel catalogue={layers.data} />
        <SidePanel status={status.data} />
      </main>

      <TabBar />

      <AnalysisDrawer />
      <ErrorSheet />
    </div>
  );
}
