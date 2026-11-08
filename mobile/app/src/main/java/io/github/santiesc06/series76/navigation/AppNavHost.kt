package io.github.santiesc06.series76.navigation

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import io.github.santiesc06.series76.data.auth.AuthState
import io.github.santiesc06.series76.data.auth.SignedInUser
import io.github.santiesc06.series76.devtools.DevTools
import io.github.santiesc06.series76.ui.chat.ChatScreen
import io.github.santiesc06.series76.ui.common.LoadingState
import io.github.santiesc06.series76.ui.conversations.ConversationsScreen
import io.github.santiesc06.series76.ui.login.LoginScreen
import kotlinx.serialization.Serializable

@Serializable
object ConversationsRoute

/** `sessionId == null` opens an empty chat; the backend creates the session on the first message. */
@Serializable
data class ChatRoute(val sessionId: String? = null)

/**
 * Login screen or app, from the session state (US-21 AC7). The app's navigation is built fresh on
 * every sign-in, so nothing from the previous user stays on the back stack or in its ViewModels.
 */
@Composable
fun AppRoot(viewModel: AppViewModel = hiltViewModel()) {
    val auth by viewModel.auth.collectAsStateWithLifecycle()
    when (val state = auth) {
        AuthState.Loading -> Surface(Modifier.fillMaxSize()) { LoadingState() }
        is AuthState.SignedOut -> LoginScreen(sessionExpired = state.expired)
        is AuthState.SignedIn -> AppNavHost(user = state.user, onLogout = viewModel::logout)
    }
}

@Composable
private fun AppNavHost(user: SignedInUser, onLogout: () -> Unit) {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = ConversationsRoute) {
        composable<ConversationsRoute> {
            ConversationsScreen(
                user = user,
                onLogout = onLogout,
                onOpen = { id -> navController.navigate(ChatRoute(sessionId = id)) },
                onNew = { navController.navigate(ChatRoute()) },
            )
        }
        composable<ChatRoute> {
            ChatScreen(
                onBack = { navController.popBackStack() },
                // Only the debug build has the developer screen (design M5, US-19 AC2).
                onOpenDebug = if (DevTools.ENABLED) {
                    { messageId -> DevTools.openMessageDetails(navController, messageId) }
                } else {
                    null
                },
            )
        }
        DevTools.registerDestinations(this, navController)
    }
}
