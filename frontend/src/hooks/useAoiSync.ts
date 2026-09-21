/** Keeps the validated AOI measurements in step with the drawn geometry. */

import { useEffect } from 'react';

import { useStore } from '../state/store';
import { useWorkflow } from './useWorkflow';

export function useAoiSync() {
  const geometry = useStore((s) => s.geometry);
  const drawMode = useStore((s) => s.drawMode);
  const setAoi = useStore((s) => s.setAoi);
  const { validate } = useWorkflow();

  useEffect(() => {
    if (!geometry) {
      setAoi(null);
      return;
    }
    // Measuring mid-draw would show an area for an unfinished shape.
    if (drawMode === 'drawing') return;
    void validate();
  }, [geometry, drawMode, setAoi, validate]);
}
