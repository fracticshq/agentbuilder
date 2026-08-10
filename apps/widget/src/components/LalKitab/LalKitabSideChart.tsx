import React from 'react';
import { KundaliChart } from '../KundaliChart';
import type { KundaliChartData } from '../../types';

interface LalKitabSideChartProps {
  kundaliChart: KundaliChartData | null;
  reportText?: string;
}

/** Compact chart + mini report shown as the left column next to chat,
 * inside the same panel (see ChatWindow's `sideChart` slot) — chart and
 * chat are one interface, not separate screens. */
export const LalKitabSideChart: React.FC<LalKitabSideChartProps> = ({ kundaliChart, reportText }) => {
  return (
    <div className="lk-workspace-chart-col lk-workspace-chart-col-wide" style={{ height: '100%', width: '100%' }}>
      {kundaliChart ? (
        <KundaliChart data={kundaliChart} />
      ) : (
        <div className="lk-report-mini">Your chart is being prepared…</div>
      )}
      {reportText && (
        <div className="lk-report-mini">
          <strong>Reading</strong>
          {reportText.slice(0, 260)}
          {reportText.length > 260 ? '…' : ''}
        </div>
      )}
    </div>
  );
};
