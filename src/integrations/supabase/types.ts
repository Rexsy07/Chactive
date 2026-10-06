export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      bookmarks: {
        Row: {
          created_at: string
          post_id: number
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          post_id: number
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          post_id?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "bookmarks_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      campus_news: {
        Row: {
          campus: string
          created_at: string
          id: number
          image_url: string | null
          published_at: string
          source: string
          summary: string
          title: string
          updated_at: string
        }
        Insert: {
          campus: string
          created_at?: string
          id?: number
          image_url?: string | null
          published_at?: string
          source: string
          summary?: string
          title: string
          updated_at?: string
        }
        Update: {
          campus?: string
          created_at?: string
          id?: number
          image_url?: string | null
          published_at?: string
          source?: string
          summary?: string
          title?: string
          updated_at?: string
        }
        Relationships: []
      }
      comments: {
        Row: {
          author_id: string
          body: string
          created_at: string
          handle: string
          id: number
          post_id: number
          updated_at: string
        }
        Insert: {
          author_id: string
          body: string
          created_at?: string
          handle: string
          id?: number
          post_id: number
          updated_at?: string
        }
        Update: {
          author_id?: string
          body?: string
          created_at?: string
          handle?: string
          id?: number
          post_id?: number
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "comments_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      direct_messages: {
        Row: {
          body: string
          created_at: string
          id: number
          recipient_id: string
          sender_id: string
          updated_at: string
        }
        Insert: {
          body: string
          created_at?: string
          id?: number
          recipient_id: string
          sender_id: string
          updated_at?: string
        }
        Update: {
          body?: string
          created_at?: string
          id?: number
          recipient_id?: string
          sender_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "direct_messages_recipient_id_fkey"
            columns: ["recipient_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "direct_messages_sender_id_fkey"
            columns: ["sender_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      follows: {
        Row: {
          created_at: string
          target: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          target: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          target?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      poll_votes: {
        Row: {
          choice: string
          created_at: string
          post_id: number
          updated_at: string
          user_id: string
        }
        Insert: {
          choice: string
          created_at?: string
          post_id: number
          updated_at?: string
          user_id: string
        }
        Update: {
          choice?: string
          created_at?: string
          post_id?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "poll_votes_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      post_votes: {
        Row: {
          created_at: string
          post_id: number
          updated_at: string
          user_id: string
          value: number
        }
        Insert: {
          created_at?: string
          post_id: number
          updated_at?: string
          user_id: string
          value: number
        }
        Update: {
          created_at?: string
          post_id?: number
          updated_at?: string
          user_id?: string
          value?: number
        }
        Relationships: [
          {
            foreignKeyName: "post_votes_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "posts"
            referencedColumns: ["id"]
          },
        ]
      }
      posts: {
        Row: {
          author_id: string | null
          body: string
          campus: string
          comments: number
          created_at: string
          flair: string
          handle: string
          id: number
          kind: string
          media_url: string | null
          title: string
          updated_at: string
          votes: number
        }
        Insert: {
          author_id?: string | null
          body?: string
          campus: string
          comments?: number
          created_at?: string
          flair?: string
          handle: string
          id?: number
          kind?: string
          media_url?: string | null
          title: string
          updated_at?: string
          votes?: number
        }
        Update: {
          author_id?: string | null
          body?: string
          campus?: string
          comments?: number
          created_at?: string
          flair?: string
          handle?: string
          id?: number
          kind?: string
          media_url?: string | null
          title?: string
          updated_at?: string
          votes?: number
        }
        Relationships: []
      }
      profiles: {
        Row: {
          bio: string
          campus: string
          created_at: string
          display_name: string
          handle: string
          id: string
          joined_at: string
          updated_at: string
        }
        Insert: {
          bio?: string
          campus?: string
          created_at?: string
          display_name: string
          handle: string
          id: string
          joined_at?: string
          updated_at?: string
        }
        Update: {
          bio?: string
          campus?: string
          created_at?: string
          display_name?: string
          handle?: string
          id?: string
          joined_at?: string
          updated_at?: string
        }
        Relationships: []
      }
      room_messages: {
        Row: {
          author_id: string
          body: string
          campus: string
          created_at: string
          id: number
          room: string
          updated_at: string
        }
        Insert: {
          author_id: string
          body: string
          campus: string
          created_at?: string
          id?: number
          room: string
          updated_at?: string
        }
        Update: {
          author_id?: string
          body?: string
          campus?: string
          created_at?: string
          id?: number
          room?: string
          updated_at?: string
        }
        Relationships: []
      }
      rooms: {
        Row: {
          author_id: string | null
          campus: string
          created_at: string
          id: number
          name: string
          updated_at: string
        }
        Insert: {
          author_id?: string | null
          campus: string
          created_at?: string
          id?: number
          name: string
          updated_at?: string
        }
        Update: {
          author_id?: string | null
          campus?: string
          created_at?: string
          id?: number
          name?: string
          updated_at?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
