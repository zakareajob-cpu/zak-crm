package com.zakcrm.spacecat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.hypot
import kotlin.random.Random

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SpaceCatGame()
        }
    }
}

data class Planet(val x: Float, val y: Float, val radius: Float, val color: Color)

@Composable
fun SpaceCatGame() {
    val planets = remember {
        listOf(
            Planet(0.18f, 0.78f, 0.1f, Color(0xFFFFAA33)),
            Planet(0.42f, 0.60f, 0.095f, Color(0xFF77DD77)),
            Planet(0.67f, 0.43f, 0.09f, Color(0xFF66CCFF)),
            Planet(0.85f, 0.24f, 0.11f, Color(0xFFFF77AA))
        )
    }

    var planetIndex by remember { mutableIntStateOf(0) }
    var stars by remember { mutableStateOf(generateStars()) }
    var score by remember { mutableIntStateOf(0) }
    val progress = remember { Animatable(0f) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(1800)
            stars = generateStars()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(Color(0xFF12002B), Color(0xFF330867), Color(0xFF5F0A87))
                )
            )
            .pointerInput(planetIndex) {
                detectTapGestures {
                    if (planetIndex < planets.lastIndex) {
                        val from = planets[planetIndex]
                        val to = planets[planetIndex + 1]
                        launch {
                            progress.snapTo(0f)
                            progress.animateTo(
                                targetValue = 1f,
                                animationSpec = tween(durationMillis = 420)
                            )
                            val jumped = distance(from, to)
                            score += (jumped * 100).toInt()
                            planetIndex += 1
                            progress.snapTo(0f)
                        }
                    } else {
                        planetIndex = 0
                        score = 0
                        progress.snapTo(0f)
                    }
                }
            }
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            stars.forEach { (x, y, size, alpha) ->
                drawCircle(
                    color = Color.White.copy(alpha = alpha),
                    radius = size,
                    center = Offset(x * size.width, y * size.height)
                )
            }

            planets.forEachIndexed { index, planet ->
                val center = Offset(planet.x * size.width, planet.y * size.height)
                drawCircle(
                    color = planet.color,
                    radius = planet.radius * size.minDimension,
                    center = center
                )
                drawCircle(
                    color = Color.White.copy(alpha = 0.5f),
                    radius = planet.radius * size.minDimension * 0.55f,
                    center = Offset(center.x - 20, center.y - 20),
                    style = Stroke(width = 6f)
                )

                if (index < planets.lastIndex) {
                    val next = planets[index + 1]
                    drawLine(
                        color = Color.White.copy(alpha = 0.15f),
                        start = center,
                        end = Offset(next.x * size.width, next.y * size.height),
                        strokeWidth = 4f
                    )
                }
            }

            val from = planets[planetIndex]
            val to = planets.getOrElse(planetIndex + 1) { planets[planetIndex] }
            val catX = (from.x + (to.x - from.x) * progress.value) * size.width
            val catY = (from.y + (to.y - from.y) * progress.value) * size.height

            drawCircle(
                color = Color(0xFFFFF0A8),
                radius = 28f,
                center = Offset(catX, catY)
            )
            drawCircle(color = Color.Black, radius = 4f, center = Offset(catX - 9f, catY - 4f))
            drawCircle(color = Color.Black, radius = 4f, center = Offset(catX + 9f, catY - 4f))
            drawCircle(color = Color(0xFFFF88A0), radius = 6f, center = Offset(catX, catY + 7f))
        }

        Text(
            text = "Space Cat Jump",
            color = Color(0xFFFFF59D),
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 20.dp)
        )

        Text(
            text = "Score: $score",
            color = Color.White,
            fontSize = 20.sp,
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 16.dp, top = 76.dp)
        )

        Text(
            text = if (planetIndex < planets.lastIndex) {
                "Tap to jump to the next planet!"
            } else {
                "You reached the rainbow planet! Tap to play again!"
            },
            color = Color(0xFFD6F6FF),
            fontSize = 18.sp,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 28.dp)
        )
    }
}

private fun distance(a: Planet, b: Planet): Float {
    return hypot(a.x - b.x, a.y - b.y)
}

private fun generateStars(): List<Star> = List(60) {
    Star(
        x = Random.nextFloat(),
        y = Random.nextFloat(),
        size = Random.nextFloat() * 4f + 1f,
        alpha = Random.nextFloat() * 0.6f + 0.2f
    )
}

data class Star(val x: Float, val y: Float, val size: Float, val alpha: Float)
