// React lifecycle wrapper around ShareSocket for the public shared-agent page:
// creates one anonymous socket per (linkId, visitorId), tracks its connection
// status, and disposes it on unmount. Create-in-effect / dispose-in-cleanup
// keeps it StrictMode-safe (the double-invoked mount just handshakes twice).

import { useEffect, useState } from 'react';
import { ShareSocket, type ShareSocketStatus } from '~/lib/socket/share-socket';

export function useShareSocket(
  linkId: string,
  visitorId: string,
): { socket: ShareSocket | null; status: ShareSocketStatus } {
  const [socket, setSocket] = useState<ShareSocket | null>(null);
  const [status, setStatus] = useState<ShareSocketStatus>('connecting');

  useEffect(() => {
    const s = new ShareSocket({ share_link_id: linkId, visitor_id: visitorId });
    setSocket(s);
    setStatus(s.getStatus());
    const offStatus = s.onStatus(setStatus);
    return () => {
      offStatus();
      s.dispose();
      setSocket(null);
    };
  }, [linkId, visitorId]);

  return { socket, status };
}
