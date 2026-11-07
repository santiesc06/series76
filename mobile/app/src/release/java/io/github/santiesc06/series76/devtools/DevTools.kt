package io.github.santiesc06.series76.devtools

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController

/** Release builds: no developer screen at all (design M5, US-19 AC2). */
object DevTools {
    const val ENABLED = false

    fun registerDestinations(builder: NavGraphBuilder, navController: NavHostController) = Unit

    fun openMessageDetails(navController: NavHostController, messageId: String) = Unit
}
