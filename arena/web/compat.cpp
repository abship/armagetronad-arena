/*
 * Armagetron Advanced browser compatibility shims.
 * Copyright (C) 2026 The Armagetron Advanced Development Team
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version.
 */

#include <SDL.h>

extern "C" SDL_AudioSpec * SDL_LoadWAV_RW( SDL_RWops *, int,
                                            SDL_AudioSpec *, Uint8 **,
                                            Uint32 * )
{
    return 0;
}

extern "C" void SDL_FreeWAV( Uint8 * audio )
{
    SDL_free( audio );
}

extern "C" int SDL_BuildAudioCVT( SDL_AudioCVT *, Uint16, Uint8, int,
                                   Uint16, Uint8, int )
{
    return -1;
}

extern "C" int SDL_ConvertAudio( SDL_AudioCVT * )
{
    return -1;
}
