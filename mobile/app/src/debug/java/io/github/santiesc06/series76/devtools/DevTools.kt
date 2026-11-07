package io.github.santiesc06.series76.devtools

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.composable
import kotlinx.serialization.Serializable

@Serializable
data class DebugRoute(val messageId: String)

/**
 * Debug builds only (design M5): the developer screen for one assistant answer, opened by
 * long-pressing it in the chat. The release source set has a no-op twin of this object.
 */
object DevTools {
    const val ENABLED = true

    fun registerDestinations(builder: NavGraphBuilder, navController: NavHostController) {
        builder.composable<DebugRoute> {
            DebugScreen(onBack = { navController.popBackStack() })
        }
    }

    fun openMessageDetails(navController: NavHostController, messageId: String) {
        navController.navigate(DebugRoute(messageId))
    }
}
