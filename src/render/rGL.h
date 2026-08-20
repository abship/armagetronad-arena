#ifndef AT_GL_H
#define AT_GL_H

#ifndef DEDICATED

#ifdef WIN32
#include <windows.h>
#endif


#define NO_SDL_GLEXT
#include <SDL_opengl.h>
#ifdef __EMSCRIPTEN__
#include <GL/glu.h>

#define glTexCoord2d( x, y ) glTexCoord2f( static_cast< GLfloat >( x ), static_cast< GLfloat >( y ) )
#define glTexCoord3fv( v ) glTexCoord2f( (v)[0], (v)[1] )
inline void sr_glRectf( GLfloat x1, GLfloat y1, GLfloat x2, GLfloat y2 )
{
    glBegin( GL_QUADS );
    glVertex2f( x1, y1 );
    glVertex2f( x2, y1 );
    glVertex2f( x2, y2 );
    glVertex2f( x1, y2 );
    glEnd();
}
#define glRectf( x1, y1, x2, y2 ) sr_glRectf( x1, y1, x2, y2 )
#endif

/*
// include OpenGL header
#ifdef HAVE_SDL_OPENGL_H
#include <SDL_opengl.h>
#else
#ifdef HAVE_SDL_SDL_OPENGL_H
#include <SDL/SDL_opengl.h>
#else
#ifdef HAVE_OPENGL_GL_H
#include <OpenGL/gl.h>
#include <OpenGL/glu.h>
#else
#ifdef HAVE_GL_GL_H
#include <GL/gl.h>
#include <GL/glu.h>
#else
#error No suitable OpenGL header found by configure!
#endif
#endif
#endif
#endif
*/

#else

typedef float GLfloat;
typedef unsigned char GLubyte;
typedef unsigned int GLuint;
typedef unsigned int GLenum;
#endif


#ifdef DEBUG
#ifndef DEDICATED
#define AA_GL_ERROR_CHECKING
#endif
#endif

#ifdef AA_GL_ERROR_CHECKING
//! for debugging purposes: checks for OpenGL errors and prints them to the console.
void sr_CheckGLError();
#else
inline void sr_CheckGLError(){}
#endif

#endif
