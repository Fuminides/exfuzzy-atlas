import { createContext, useContext } from "react";
import { DEFAULT_ZONE } from "./format";

/** IANA zone of the entities on screen (`properties.timezone`): local times are shown in it, never assumed to be Madrid. */
export const ZoneContext = createContext<string>(DEFAULT_ZONE);
export const useZone = (): string => useContext(ZoneContext);
