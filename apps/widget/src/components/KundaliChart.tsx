import React from 'react';
import type { KundaliChartData, KundaliHouse } from '../types';

/**
 * Traditional North-Indian (diamond) kundali chart, rendered as an inline SVG
 * artifact above the astrologer's reading. Drawn purely from the structured
 * `kundali_chart` metadata calculated by the backend — never guessed.
 *
 * Layout (400×400 viewBox): outer square, both diagonals, and the inner
 * diamond joining the edge midpoints. That yields the 12 fixed house regions:
 * four kites around the centre (1 top, 4 left, 7 bottom, 10 right) and eight
 * corner triangles (2/3 top-left, 5/6 bottom-left, 8/9 bottom-right,
 * 11/12 top-right).
 */

const SIZE = 400;

/** Where each house's planet cluster sits. */
const PLANET_POS: Record<number, [number, number]> = {
  1: [200, 92],
  2: [100, 46],
  3: [46, 102],
  4: [112, 200],
  5: [46, 298],
  6: [100, 356],
  7: [200, 308],
  8: [300, 356],
  9: [356, 298],
  10: [290, 200],
  11: [356, 102],
  12: [300, 46],
};

/** Where each house's number label sits (near the inner intersections). */
const HOUSE_NUM_POS: Record<number, [number, number]> = {
  1: [200, 168],
  2: [110, 88],
  3: [88, 112],
  4: [182, 200],
  5: [88, 288],
  6: [110, 314],
  7: [200, 234],
  8: [290, 314],
  9: [312, 288],
  10: [220, 200],
  11: [312, 112],
  12: [290, 88],
};

/** Corner triangles hold at most ~2 codes per line comfortably. */
const NARROW_HOUSES = new Set([2, 3, 5, 6, 8, 9, 11, 12]);

const INK = '#9b1c1c';        // maroon lines + planet labels
const NUM_COLOR = '#3b3b3b';  // house numbers
const BG = '#fcf7d9';         // pale-yellow parchment

const chunk = <T,>(items: T[], size: number): T[][] => {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
};

const PlanetLabels: React.FC<{ house: KundaliHouse }> = ({ house }) => {
  const planets = house.planets || [];
  if (!planets.length) return null;
  const [cx, cy] = PLANET_POS[house.house];
  const perLine = NARROW_HOUSES.has(house.house) ? 2 : 3;
  const lines = chunk(planets, perLine);
  const lineHeight = 17;
  const startY = cy - ((lines.length - 1) * lineHeight) / 2;
  return (
    <text
      x={cx}
      y={startY}
      textAnchor="middle"
      dominantBaseline="middle"
      fontSize="15"
      fontWeight={600}
      fill={INK}
      style={{ fontFamily: 'Georgia, "Noto Serif", serif' }}
    >
      {lines.map((line, index) => (
        <tspan key={index} x={cx} dy={index === 0 ? 0 : lineHeight}>
          {line.join(' ')}
        </tspan>
      ))}
    </text>
  );
};

export const KundaliChart: React.FC<{ data: KundaliChartData }> = ({ data }) => {
  const houses = data.houses || [];
  if (!houses.length) return null;

  const birthBits = [data.birth?.name, data.birth?.date, data.birth?.time, data.birth?.place].filter(Boolean);
  const lagna = data.ascendant
    ? `Lagna: ${data.ascendant.name}${data.ascendant.hindi ? ` (${data.ascendant.hindi})` : ''}`
    : '';
  const caption = [birthBits.join(' • '), lagna].filter(Boolean).join('  —  ');

  return (
    <div
      className="kundali-chart"
      style={{
        background: BG,
        border: `2px solid ${INK}`,
        borderRadius: 8,
        padding: '10px 10px 6px',
        margin: '4px 0 10px',
        maxWidth: 360,
      }}
    >
      <div
        style={{
          textAlign: 'center',
          color: INK,
          fontFamily: 'Georgia, "Noto Serif", serif',
          fontWeight: 700,
          fontSize: 13,
          letterSpacing: '0.08em',
          marginBottom: 6,
        }}
      >
        लाल किताब कुंडली · LAL KITAB KUNDALI
      </div>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label="Lal Kitab kundali chart"
        style={{ width: '100%', height: 'auto', display: 'block' }}
      >
        {/* frame */}
        <rect x="2" y="2" width={SIZE - 4} height={SIZE - 4} fill={BG} stroke={INK} strokeWidth="2.5" />
        {/* diagonals */}
        <line x1="2" y1="2" x2={SIZE - 2} y2={SIZE - 2} stroke={INK} strokeWidth="1.6" />
        <line x1={SIZE - 2} y1="2" x2="2" y2={SIZE - 2} stroke={INK} strokeWidth="1.6" />
        {/* inner diamond */}
        <polygon
          points={`${SIZE / 2},2 ${SIZE - 2},${SIZE / 2} ${SIZE / 2},${SIZE - 2} 2,${SIZE / 2}`}
          fill="none"
          stroke={INK}
          strokeWidth="1.6"
        />
        {/* house numbers */}
        {houses.map((house) => {
          const pos = HOUSE_NUM_POS[house.house];
          if (!pos) return null;
          return (
            <text
              key={`num-${house.house}`}
              x={pos[0]}
              y={pos[1]}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize="13"
              fill={NUM_COLOR}
              style={{ fontFamily: 'Georgia, "Noto Serif", serif' }}
            >
              {house.house}
            </text>
          );
        })}
        {/* planets */}
        {houses.map((house) =>
          PLANET_POS[house.house] ? <PlanetLabels key={`pl-${house.house}`} house={house} /> : null,
        )}
      </svg>
      {caption && (
        <div
          style={{
            textAlign: 'center',
            color: '#6b5335',
            fontFamily: 'Georgia, "Noto Serif", serif',
            fontSize: 11.5,
            marginTop: 6,
          }}
        >
          {caption}
        </div>
      )}
      <div
        style={{
          textAlign: 'center',
          color: '#8a6d3b',
          fontFamily: 'Georgia, "Noto Serif", serif',
          fontSize: 10,
          marginTop: 2,
        }}
      >
        Su Sun · Mo Moon · Ma Mars · Me Mercury · Ju Jupiter · Ve Venus · Sa Saturn · Ra Rahu · Ke Ketu
      </div>
    </div>
  );
};
