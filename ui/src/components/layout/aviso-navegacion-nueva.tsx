'use client';

import { useEffect } from 'react';
import { toast } from 'sonner';

import { agregarBreadcrumb } from '@/lib/telemetria';
import { useAuth } from '@/providers/auth-provider';
import { useNavegacion } from '@/providers/navegacion-provider';

/** La instalación ya vio el aviso de la navegación nueva (fase 2). */
const LLAVE_AVISO = 'tc:navegacion-aviso-visto';

/**
 * Aviso de una sola vez para quien usaba la navegación clásica y la fase 2
 * (`NAV_ESPACIOS_PARA_TODOS`) le cambió a espacios: le dice que nada se borró y
 * le deja volver a la clásica en un clic. Las cuentas nuevas o en prueba ya
 * arrancaron en espacios (origen 'prueba' o 'recordado') y no lo ven.
 */
export function AvisoNavegacionNueva() {
  const { license } = useAuth();
  const { listo, origen, setPreferencia } = useNavegacion();

  useEffect(() => {
    if (!listo || !license?.authenticated || origen !== 'para-todos') return;
    try {
      if (localStorage.getItem(LLAVE_AVISO)) return;
      localStorage.setItem(LLAVE_AVISO, '1');
    } catch {
      return; // sin storage, mejor no avisar en cada carga
    }
    agregarBreadcrumb({ category: 'nav', message: 'aviso navegación nueva' });
    toast('TodoConta tiene nueva navegación', {
      description:
        'Todo sigue ahí, acomodado en 5 espacios. Si no encuentras algo, puedes volver a la clásica cuando quieras en Ajustes, Apariencia, Navegación.',
      duration: 20000,
      action: {
        label: 'Volver a la clásica',
        onClick: () => setPreferencia('clasica'),
      },
    });
  }, [listo, license?.authenticated, origen, setPreferencia]);

  return null;
}
