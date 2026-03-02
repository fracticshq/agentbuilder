import { useState, useEffect } from 'react';

export function useCyclingText(items: string[], interval = 2200) {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (!items.length) return;
    const timer = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIndex(i => (i + 1) % items.length);
        setVisible(true);
      }, 400); // matches transition duration
    }, interval);
    return () => clearInterval(timer);
  }, [items, interval]);

  return { text: items[index] ?? '', visible };
}
