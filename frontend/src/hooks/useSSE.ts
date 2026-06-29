import { useEffect, useRef, useCallback } from 'react';

type EventHandler = (data: Record<string, unknown>) => void;

/**
 * SSE hook — регистрирует слушатели динамически по ключам объекта handlers.
 * Новые события подхватываются автоматически без хардкода списка.
 */
export function useSSE(url: string, handlers: Record<string, EventHandler>) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  // Набор уже зарегистрированных имён событий на текущем EventSource
  const registeredRef = useRef<Set<string>>(new Set());

  const registerEvents = useCallback((es: EventSource) => {
    const system = new Set(['__open', '__error']);
    for (const eventName of Object.keys(handlersRef.current)) {
      if (system.has(eventName) || registeredRef.current.has(eventName)) continue;
      registeredRef.current.add(eventName);
      es.addEventListener(eventName, (e: Event) => {
        try {
          const data = JSON.parse((e as MessageEvent).data);
          handlersRef.current[eventName]?.(data);
        } catch {}
      });
    }
  }, []);

  const connect = useCallback(() => {
    eventSourceRef.current?.close();
    registeredRef.current.clear();

    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      handlersRef.current['__open']?.({});
      // Регистрируем текущие обработчики после открытия
      registerEvents(es);
    };

    es.onerror = () => {
      handlersRef.current['__error']?.({});
      setTimeout(connect, 2000);
    };

    // Регистрируем немедленно (onopen может не сработать если уже открыт)
    registerEvents(es);
  }, [url, registerEvents]);

  // Если в handlers появились новые ключи — дорегистрируем без пересоздания соединения
  useEffect(() => {
    handlersRef.current = handlers;
    if (eventSourceRef.current) {
      registerEvents(eventSourceRef.current);
    }
  });

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { reconnect: connect };
}
